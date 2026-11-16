/* Research capture for the VFS7552: N scans per named finger.
 * Usage (root): vfs-capture OUTDIR SCANS finger1 [finger2 ...]
 * Writes OUTDIR/<finger>/<n>/ raw frames (via the driver's research hook),
 * OUTDIR/<finger>/<n>.pgm (the image libfprint matches on) and OUTDIR/status. */
#include <fprint.h>
#include <glib.h>
#include <glib/gstdio.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static const char *outdir;

static void
status (const char *fmt, ...)
{
  va_list ap;
  g_autofree char *msg = NULL;
  g_autofree char *path = g_build_filename (outdir, "status", NULL);

  va_start (ap, fmt);
  msg = g_strdup_vprintf (fmt, ap);
  va_end (ap);
  g_file_set_contents (path, msg, -1, NULL);
  printf ("%s\n", msg);
  fflush (stdout);
}

int
main (int argc, char **argv)
{
  g_autoptr(FpContext) ctx = NULL;
  g_autoptr(GError) error = NULL;
  GPtrArray *devices;
  FpDevice *dev;
  int scans;

  if (argc < 4)
    {
      fprintf (stderr, "usage: %s OUTDIR SCANS finger...\n", argv[0]);
      return 2;
    }
  outdir = argv[1];
  scans = atoi (argv[2]);

  ctx = fp_context_new ();
  devices = fp_context_get_devices (ctx);
  if (!devices || devices->len == 0)
    {
      status ("error no reader");
      return 1;
    }
  dev = g_ptr_array_index (devices, 0);
  if (!fp_device_open_sync (dev, NULL, &error))
    {
      status ("error open %s", error->message);
      return 1;
    }

  for (int f = 3; f < argc; f++)
    {
      g_auto(GStrv) spec = g_strsplit (argv[f], ":", 2);
      int count = spec[1] ? atoi (spec[1]) : scans;
      g_autofree char *fdir = g_build_filename (outdir, spec[0], NULL);
      argv[f] = g_strdup (spec[0]);
      g_mkdir_with_parents (fdir, 0755);
      scans = count;
      status ("switch %s 0 %d", argv[f], scans);
      sleep (6);
      for (int n = 1; n <= scans; n++)
        {
          g_autofree char *sdir = g_strdup_printf ("%s/%02d", fdir, n);
          g_autofree char *pgm = g_strdup_printf ("%s/%02d.pgm", fdir, n);
          g_autoptr(FpImage) img = NULL;
          g_autoptr(GError) cerr = NULL;
          const guchar *data;
          gsize len;
          FILE *fp;

          g_mkdir_with_parents (sdir, 0755);
          g_setenv ("ADAPTIVE_VFS7552_DUMP", sdir, TRUE);
          status ("touch %s %d %d", argv[f], n, scans);
          img = fp_device_capture_sync (dev, TRUE, NULL, &cerr);
          g_setenv ("ADAPTIVE_VFS7552_DUMP", "", TRUE);
          if (!img)
            {
              status ("retry %s %d %d %s", argv[f], n, scans, cerr->message);
              n--;
              sleep (1);
              continue;
            }
          data = fp_image_get_data (img, &len);
          fp = fopen (pgm, "wb");
          fprintf (fp, "P5\n%u %u\n255\n", fp_image_get_width (img), fp_image_get_height (img));
          fwrite (data, 1, len, fp);
          fclose (fp);
          status ("captured %s %d %d", argv[f], n, scans);
          sleep (2); /* time to lift */
        }
    }
  status ("done");
  fp_device_close_sync (dev, NULL, NULL);
  return 0;
}
