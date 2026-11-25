/* Load a packaged module order on the reference kernel. */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/reboot.h>
#include <sys/syscall.h>
#include <unistd.h>

int main(int argc, char **argv) {
    const char *order = "/module-order";
    if (argc == 2 && !strcmp(argv[1], "--without-touch"))
        order = "/module-order-without-touch";
    else if (argc != 1)
        return 1;
    setvbuf(stdout, NULL, _IOLBF, 0);
    FILE *list = fopen(order, "r");
    if (!list) {
        perror("open module list");
        return 1;
    }
    int failed = 0;
    char name[256];
    while (fgets(name, sizeof(name), list)) {
        name[strcspn(name, "\n")] = 0;
        char path[300];
        snprintf(path, sizeof(path), "/lib/modules/%s", name);
        printf("AIOS_MODULE_TRY %s\n", name);
        int fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd < 0) {
            perror(path);
            return 1;
        }
        int error = syscall(SYS_finit_module, fd, "", 0) == 0 ? 0 : errno;
        close(fd);
        failed |= error != 0;
        printf("AIOS_MODULE_RESULT %s %d\n", name, error);
    }
    fclose(list);
    puts("AIOS_MODULE_PROBE_DONE");
    if (getpid() != 1)
        return failed;
    return reboot(RB_POWER_OFF);
}
