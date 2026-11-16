/* Offline scorer using libfprint's own NBIS pipeline.
 * Usage: vfs-score img1.pgm img2.pgm ...   (8-bit P5 images)
 * Prints "M i n" (minutiae count per image) then the full bozorth3 score
 * matrix "S i j score" (probe i against single-sample gallery j). */
#include "fpi-image.h"
#include "fpi-print.h"
#include "fp-print-private.h"
#include "fpi-log.h"
#include <bozorth.h>
#include <stdio.h>
#include <stdlib.h>

static FpImage *
load_pgm (const char *path)
{
  FILE *fp = fopen (path, "rb");
  int w, h, max;
  FpImage *img;

  if (!fp || fscanf (fp, "P5 %d %d %d", &w, &h, &max) != 3)
    return NULL;
  fgetc (fp);
  img = fp_image_new (w, h);
  if (fread (img->data, 1, w * h, fp) != (size_t) (w * h))
    return NULL;
  fclose (fp);
  return img;
}

static void
on_detected (GObject *src, GAsyncResult *res, gpointer user_data)
{
  g_autoptr(GError) error = NULL;
  fp_image_detect_minutiae_finish (FP_IMAGE (src), res, &error);
  *(gboolean *) user_data = TRUE;
}

int
main (int argc, char **argv)
{
  int n = argc - 1;
  struct xyt_struct **xyt = g_new0 (struct xyt_struct *, n);

  for (int i = 0; i < n; i++)
    {
      g_autoptr(FpImage) img = load_pgm (argv[i + 1]);
      g_autoptr(GError) error = NULL;
      FpPrint *print;

      if (!img)
        {
          fprintf (stderr, "cannot read %s\n", argv[i + 1]);
          return 1;
        }
      {
        gboolean done = FALSE;
        fp_image_detect_minutiae (img, NULL, on_detected, &done);
        while (!done)
          g_main_context_iteration (NULL, TRUE);
      }
      print = g_object_new (FP_TYPE_PRINT, "driver", "vfs7552", "device-id", "research", NULL);
      fpi_print_set_type (print, FPI_PRINT_NBIS);
      if (!fpi_print_add_from_image (print, img, &error))
        {
          printf ("M %d 0\n", i);
          continue;
        }
      xyt[i] = g_ptr_array_index (print->prints, 0);
      printf ("M %d %d\n", i, xyt[i]->nrows);
    }

  for (int i = 0; i < n; i++)
    {
      int plen;
      if (!xyt[i])
        continue;
      plen = bozorth_probe_init (xyt[i]);
      for (int j = 0; j < n; j++)
        if (j != i && xyt[j])
          printf ("S %d %d %d\n", i, j, bozorth_to_gallery (plen, xyt[i], xyt[j]));
    }
  return 0;
}
