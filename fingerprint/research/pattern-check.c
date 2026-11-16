/* Offline check of the shipped VFS7552 pipeline: driver image processing +
 * libfprint pattern matcher, on recorded raw frames.
 * Usage: pattern-check LISTFILE   (lines: "label bgfile framefile")
 * Prints "K i keypoints" then "S i j score" for all ordered pairs. */
#include <stdio.h>
#include "fpi-pattern.h"
#include "drivers/vfs7552_image.h"

int
main (int argc, char **argv)
{
  FILE *list = fopen (argv[1], "r");
  char label[128], bgp[1024], frp[1024];
  GPtrArray *f = g_ptr_array_new ();

  while (fscanf (list, "%127s %1023s %1023s", label, bgp, frp) == 3)
    {
      g_autofree guchar *bg = NULL, *fr = NULL;
      gsize lb, lf;
      guint8 out[VFS7552_IMAGE_SIZE];
      GBytes *feat;
      g_autoptr(GError) err = NULL;

      g_file_get_contents (bgp, (gchar **) &bg, &lb, NULL);
      g_file_get_contents (frp, (gchar **) &fr, &lf, NULL);
      process_image (bg, fr, out);
      feat = fpi_pattern_extract (out, VFS7552_IMAGE_WIDTH, VFS7552_IMAGE_HEIGHT, &err);
      printf ("K %u %u\n", f->len, feat ? fpi_pattern_count (feat) : 0);
      g_ptr_array_add (f, feat);
    }
  for (guint i = 0; i < f->len; i++)
    for (guint j = 0; j < f->len; j++)
      if (i != j)
        printf ("S %u %u %d\n", i, j, fpi_pattern_score (g_ptr_array_index (f, i), g_ptr_array_index (f, j)));
  return 0;
}
