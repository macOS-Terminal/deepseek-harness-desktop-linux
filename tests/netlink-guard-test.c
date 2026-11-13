#define _GNU_SOURCE

/* Integration harness for libdsh-netlink-guard.so.
 * Seccomp turns recvfrom/recvmsg into EACCES without writing a single syslog
 * line.  With DSH_NETLINK_GUARD_MAX_MS=8 the expected delays are 1,2,4,8 ms.
 */

#include <errno.h>
#include <linux/filter.h>
#include <linux/netlink.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static long elapsed_ms(struct timespec start, struct timespec end) {
    return (end.tv_sec - start.tv_sec) * 1000L +
           (end.tv_nsec - start.tv_nsec) / 1000000L;
}

static long denied_recv_ms(int fd) {
    char buffer[16];
    struct timespec start, end;
    clock_gettime(CLOCK_MONOTONIC, &start);
    ssize_t result = recv(fd, buffer, sizeof(buffer), 0);
    clock_gettime(CLOCK_MONOTONIC, &end);
    if (result != -1 || errno != EACCES) {
        fprintf(stderr, "expected EACCES, got result=%zd errno=%d\n", result,
                errno);
        exit(1);
    }
    return elapsed_ms(start, end);
}

static void deny_receive_calls(void) {
    struct sock_filter instructions[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 (unsigned short)offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_recvfrom, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EACCES),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_recvmsg, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EACCES),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {
        .len = (unsigned short)(sizeof(instructions) / sizeof(instructions[0])),
        .filter = instructions,
    };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0 ||
        prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program) != 0) {
        perror("seccomp");
        exit(1);
    }
}

int main(void) {
    int fd = socket(AF_NETLINK, SOCK_RAW, NETLINK_ROUTE);
    if (fd < 0) {
        perror("socket(AF_NETLINK)");
        return 1;
    }

    /* A normal empty netlink socket returns EAGAIN immediately and must not be
       delayed or converted into another error. */
    char buffer[16];
    if (recv(fd, buffer, sizeof(buffer), MSG_DONTWAIT) != -1 ||
        (errno != EAGAIN && errno != EWOULDBLOCK)) {
        perror("initial nonblocking recv");
        return 1;
    }

    deny_receive_calls();
    long delays[5];
    for (size_t i = 0; i < 5; ++i) {
        delays[i] = denied_recv_ms(fd);
    }

    /* The same denied operation on AF_UNIX is outside the guard's scope. */
    int pair[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, pair) != 0) {
        perror("socketpair");
        return 1;
    }
    struct timespec start, end;
    clock_gettime(CLOCK_MONOTONIC, &start);
    char byte;
    ssize_t ordinary = recv(pair[0], &byte, 1, 0);
    clock_gettime(CLOCK_MONOTONIC, &end);
    if (ordinary != -1 || errno != EACCES) {
        fprintf(stderr, "AF_UNIX: expected EACCES, got result=%zd errno=%d\n",
                ordinary, errno);
        return 1;
    }
    long ordinary_ms = elapsed_ms(start, end);

    printf("netlink_delays_ms=%ld,%ld,%ld,%ld,%ld ordinary_socket_ms=%ld\n",
           delays[0], delays[1], delays[2], delays[3], delays[4],
           ordinary_ms);

    const char *expect = getenv("EXPECT_BACKOFF");
    if (expect != NULL && expect[0] == '1') {
        /* Allow scheduler jitter, but require the exponential lower bounds. */
        if (delays[0] < 1 || delays[1] < 2 || delays[2] < 4 ||
            delays[3] < 8 || delays[4] < 8) {
            fprintf(stderr, "missing capped exponential backoff\n");
            return 1;
        }
        if (ordinary_ms >= delays[3]) {
            fprintf(stderr, "ordinary socket was delayed unexpectedly\n");
            return 1;
        }
    }
    close(pair[0]);
    close(pair[1]);
    close(fd);
    return 0;
}
