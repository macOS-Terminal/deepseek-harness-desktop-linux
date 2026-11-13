#define _GNU_SOURCE

/*
 * Bounded retry backoff for Chromium's Linux netlink address tracker.
 *
 * Chromium keeps its readable-fd watcher armed after recv() fails.  A denied
 * read therefore becomes a tight PLOG(ERROR) loop.  This preload guard delays
 * only failed reads on sockets created with AF_NETLINK; all other sockets and
 * all successful reads retain their normal behavior.  The original errno is
 * always restored, so Chromium still reports the failure instead of hiding it.
 */

#include <dlfcn.h>
#include <errno.h>
#include <linux/netlink.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define FD_LIMIT 65536
#define DEFAULT_MAX_DELAY_MS 60000U
#define MAX_ALLOWED_DELAY_MS 600000U

/* Indexed by fd, so ordinary socket traffic needs only one atomic flag read. */
static atomic_uchar netlink_fds[FD_LIMIT];
static atomic_uint retry_delay_ms[FD_LIMIT];
static pthread_once_t config_once = PTHREAD_ONCE_INIT;
static int enabled = 1;
static unsigned int max_delay_ms = DEFAULT_MAX_DELAY_MS;

static void read_config(void) {
    const char *value = getenv("DSH_NETLINK_GUARD");
    if (value != NULL && value[0] == '0' && value[1] == '\0') {
        enabled = 0;
    }

    value = getenv("DSH_NETLINK_GUARD_MAX_MS");
    if (value == NULL || value[0] == '\0') {
        return;
    }
    char *end = NULL;
    errno = 0;
    unsigned long parsed = strtoul(value, &end, 10);
    if (errno == 0 && end != value && *end == '\0' && parsed > 0) {
        if (parsed > MAX_ALLOWED_DELAY_MS) {
            parsed = MAX_ALLOWED_DELAY_MS;
        }
        max_delay_ms = (unsigned int)parsed;
    }
}

static void ensure_config(void) {
    (void)pthread_once(&config_once, read_config);
}

/* Return the delay for this failure and advance that fd's exponential state. */
static unsigned int error_delay_ms(int fd, int error_number) {
    if (fd < 0 || fd >= FD_LIMIT ||
        (error_number != EACCES && error_number != EPERM &&
         error_number != ENOBUFS) ||
        atomic_load_explicit(&netlink_fds[fd], memory_order_relaxed) == 0) {
        return 0;
    }

    unsigned int delay = atomic_load_explicit(&retry_delay_ms[fd],
                                               memory_order_relaxed);
    if (delay == 0) {
        delay = 1;
    }
    unsigned int next = delay > max_delay_ms / 2 ? max_delay_ms : delay * 2;
    if (next > max_delay_ms) {
        next = max_delay_ms;
    }
    atomic_store_explicit(&retry_delay_ms[fd], next, memory_order_relaxed);
    return delay;
}

static void track_netlink_fd(int fd, int domain) {
    if (fd < 0 || fd >= FD_LIMIT || domain != AF_NETLINK) {
        return;
    }
    atomic_store_explicit(&retry_delay_ms[fd], 1, memory_order_relaxed);
    atomic_store_explicit(&netlink_fds[fd], 1, memory_order_release);
}

static void reset_fd(int fd) {
    if (fd < 0 || fd >= FD_LIMIT ||
        atomic_load_explicit(&netlink_fds[fd], memory_order_relaxed) == 0) {
        return;
    }
    if (atomic_load_explicit(&retry_delay_ms[fd], memory_order_relaxed) > 1) {
        atomic_store_explicit(&retry_delay_ms[fd], 1, memory_order_relaxed);
    }
}

static void forget_fd(int fd) {
    if (fd < 0 || fd >= FD_LIMIT) {
        return;
    }
    atomic_store_explicit(&netlink_fds[fd], 0, memory_order_release);
    atomic_store_explicit(&retry_delay_ms[fd], 0, memory_order_relaxed);
}

static void sleep_without_changing_errno(unsigned int delay_ms) {
    if (delay_ms == 0) {
        return;
    }
    struct timespec remaining = {
        .tv_sec = (time_t)(delay_ms / 1000),
        .tv_nsec = (long)(delay_ms % 1000) * 1000000L,
    };
    while (nanosleep(&remaining, &remaining) == -1 && errno == EINTR) {
    }
}

static ssize_t finish_recv(int fd, ssize_t result, int saved_errno) {
    ensure_config();
    if (result >= 0) {
        reset_fd(fd);
    } else if (enabled) {
        sleep_without_changing_errno(error_delay_ms(fd, saved_errno));
    }
    errno = saved_errno;
    return result;
}

int socket(int domain, int type, int protocol) {
    static int (*real_socket)(int, int, int) = NULL;
    if (real_socket == NULL) {
        real_socket = dlsym(RTLD_NEXT, "socket");
    }
    int fd = real_socket(domain, type, protocol);
    int saved_errno = errno;
    ensure_config();
    track_netlink_fd(fd, domain);
    errno = saved_errno;
    return fd;
}

int close(int fd) {
    static int (*real_close)(int) = NULL;
    if (real_close == NULL) {
        real_close = dlsym(RTLD_NEXT, "close");
    }
    /* Forget first so a fd immediately reused by another thread cannot inherit
       the old netlink retry state. */
    forget_fd(fd);
    return real_close(fd);
}

ssize_t recv(int fd, void *buffer, size_t length, int flags) {
    static ssize_t (*real_recv)(int, void *, size_t, int) = NULL;
    if (real_recv == NULL) {
        real_recv = dlsym(RTLD_NEXT, "recv");
    }
    ssize_t result = real_recv(fd, buffer, length, flags);
    return finish_recv(fd, result, errno);
}

ssize_t recvfrom(int fd, void *buffer, size_t length, int flags,
                 struct sockaddr *address, socklen_t *address_length) {
    static ssize_t (*real_recvfrom)(int, void *, size_t, int,
                                    struct sockaddr *, socklen_t *) = NULL;
    if (real_recvfrom == NULL) {
        real_recvfrom = dlsym(RTLD_NEXT, "recvfrom");
    }
    ssize_t result = real_recvfrom(fd, buffer, length, flags, address,
                                   address_length);
    return finish_recv(fd, result, errno);
}

ssize_t recvmsg(int fd, struct msghdr *message, int flags) {
    static ssize_t (*real_recvmsg)(int, struct msghdr *, int) = NULL;
    if (real_recvmsg == NULL) {
        real_recvmsg = dlsym(RTLD_NEXT, "recvmsg");
    }
    ssize_t result = real_recvmsg(fd, message, flags);
    return finish_recv(fd, result, errno);
}
