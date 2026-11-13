/* First trade at least one tick through each minute close, in the next 3 minutes.
   The window is (close, close + 3 minutes]. A touch that does not go through does not fill.
   stdin is a Binance aggTrades CSV. The fill array is updated and written to stdout. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#define MINUTE 60000LL
#define TICK 0.10

static int read_all(FILE *fh, void *dst, size_t bytes) {
    size_t got = 0;
    while (got < bytes) {
        size_t n = fread((char *)dst + got, 1, bytes - got, fh);
        if (n == 0) return 0;
        got += n;
    }
    return 1;
}

int main(int argc, char **argv) {
    if (argc != 6) return 2;
    long long base = atoll(argv[1]);
    long long n = atoll(argv[2]);
    long long stop = atoll(argv[5]);
    if (n < 0 || n > 5000000LL) return 3;
    FILE *cf = fopen(argv[3], "rb");
    FILE *ff = fopen(argv[4], "rb");
    if (!cf || !ff) return 4;
    double *close_at = (double *)malloc((size_t)n * sizeof(double));
    long long *fill = (long long *)malloc((size_t)n * sizeof(long long));
    if (!close_at || !fill) return 5;
    if (!read_all(cf, close_at, (size_t)n * sizeof(double))) return 6;
    if (!read_all(ff, fill, (size_t)n * sizeof(long long))) return 7;
    fclose(cf);
    fclose(ff);

    char buf[1024];
    while (fgets(buf, sizeof buf, stdin)) {
        if (buf[0] < '0' || buf[0] > '9') continue;
        char *comma = strchr(buf, ',');
        if (!comma) continue;
        char *price_s = comma + 1;
        comma = strchr(price_s, ',');
        if (!comma) continue;
        *comma = 0;
        double price = atof(price_s);
        char *q = comma + 1;
        int field;
        for (field = 0; field < 3; field++) {
            q = strchr(q, ',');
            if (!q) break;
            q++;
        }
        if (!q) continue;
        char *end = q;
        while (*end && *end != ',' && *end != '\n' && *end != '\r') end++;
        *end = 0;
        long long ts = atoll(q);
        if (ts > 100000000000000LL) ts /= 1000;
        if (stop && ts >= stop) continue;
        if (ts <= MINUTE) continue;
        long long last = ((ts - MINUTE - 1) / MINUTE) * MINUTE;
        long long raw = ts - 4 * MINUTE;
        long long first;
        if (raw <= 0) first = 0;
        else if (raw % MINUTE == 0) first = raw;
        else first = raw + (MINUTE - (raw % MINUTE));
        if (first > last) continue;
        long long slot = first / MINUTE - base;
        long long last_slot = last / MINUTE - base;
        while (slot <= last_slot) {
            if (slot >= 0 && slot < n && fill[slot] == 0) {
                double limit = close_at[slot];
                if (limit == limit && price <= limit - TICK) fill[slot] = ts;
            }
            slot++;
        }
    }
    if (fwrite(fill, sizeof(long long), (size_t)n, stdout) != (size_t)n) return 8;
    free(close_at);
    free(fill);
    return 0;
}
