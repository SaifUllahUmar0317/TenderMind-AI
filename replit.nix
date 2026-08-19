{ pkgs }: {
  deps = [
    pkgs.python311
    pkgs.tesseract
    pkgs.tesseract-data-eng
    pkgs.poppler_utils
    pkgs.zlib
    pkgs.glib
  ];
}
