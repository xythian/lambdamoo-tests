/* LD_PRELOAD fault-injection shim for network robustness tests.
 *
 * Faults are armed by creating files in the directory named by the
 * MOO_FAULT_DIR environment variable, so a test can inject them at a chosen
 * moment in a running server:
 *
 *   close-listener  Contains a port number.  On the next accept(), close the
 *                   listening socket bound to that port and the newly accepted
 *                   connection, then return the (now stale) descriptor as if
 *                   nothing happened.  The file is removed once used.  This
 *                   reproduces descriptors being closed out from under the
 *                   server's select()/poll() set.
 *
 *   fail-wait       While this file exists, select() and poll() fail with
 *                   EINVAL.
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <limits.h>
#include <netinet/in.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>

static int
fault_path(const char *name, char *buf, size_t len)
{
    const char *dir = getenv("MOO_FAULT_DIR");

    return dir && snprintf(buf, len, "%s/%s", dir, name) < (int) len;
}

static int
fault_armed(const char *name)
{
    char path[PATH_MAX];

    return fault_path(name, path, sizeof(path)) && access(path, F_OK) == 0;
}

static int
take_listener_port(void)
{
    char path[PATH_MAX];
    FILE *f;
    int port = -1;

    if (!fault_path("close-listener", path, sizeof(path))
	|| !(f = fopen(path, "r")))
	return -1;
    if (fscanf(f, "%d", &port) != 1)
	port = -1;
    fclose(f);
    unlink(path);
    return port;
}

static void
close_listener_on_port(int port)
{
    int fd;

    for (fd = 0; fd < 1024; fd++) {
	int listening = 0;
	socklen_t len = sizeof(listening);
	struct sockaddr_in addr;
	socklen_t addr_len = sizeof(addr);

	if (getsockopt(fd, SOL_SOCKET, SO_ACCEPTCONN, &listening, &len) == 0
	    && listening
	    && getsockname(fd, (struct sockaddr *) &addr, &addr_len) == 0
	    && addr.sin_family == AF_INET
	    && ntohs(addr.sin_port) == port) {
	    close(fd);
	    return;
	}
    }
}

int
accept(int sockfd, struct sockaddr *addr, socklen_t *addrlen)
{
    int (*real_accept)(int, struct sockaddr *, socklen_t *) =
	dlsym(RTLD_NEXT, "accept");
    int fd = real_accept(sockfd, addr, addrlen);
    int port;

    if (fd >= 0 && (port = take_listener_port()) >= 0) {
	close_listener_on_port(port);
	close(fd);
    }
    return fd;
}

int
select(int nfds, fd_set *readfds, fd_set *writefds, fd_set *exceptfds,
       struct timeval *timeout)
{
    int (*real_select)(int, fd_set *, fd_set *, fd_set *, struct timeval *) =
	dlsym(RTLD_NEXT, "select");

    if (fault_armed("fail-wait")) {
	errno = EINVAL;
	return -1;
    }
    return real_select(nfds, readfds, writefds, exceptfds, timeout);
}

int
poll(struct pollfd *fds, nfds_t nfds, int timeout)
{
    int (*real_poll)(struct pollfd *, nfds_t, int) = dlsym(RTLD_NEXT, "poll");

    if (fault_armed("fail-wait")) {
	errno = EINVAL;
	return -1;
    }
    return real_poll(fds, nfds, timeout);
}
