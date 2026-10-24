export function getFileCategory(name: string, mime: string = ""): string {
  const ext = (name.split(".").pop() || "").toLowerCase();
  if (mime.includes("pdf") || ext === "pdf") return "pdf";
  if (
    mime.startsWith("video/") ||
    ["mp4", "mkv", "webm", "mov", "avi", "m4v", "ts", "flv"].includes(ext)
  ) {
    return "video";
  }
  if (
    mime.startsWith("image/") ||
    ["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico"].includes(ext)
  ) {
    return "image";
  }
  if (
    mime.startsWith("audio/") ||
    ["mp3", "m4a", "flac", "wav", "ogg", "aac", "opus"].includes(ext)
  ) {
    return "audio";
  }
  if (
    ["xls", "xlsx", "csv", "ods"].includes(ext) ||
    mime.includes("sheet") ||
    mime.includes("csv")
  ) {
    return "spreadsheet";
  }
  if (
    ["doc", "docx", "odt", "rtf", "txt", "md"].includes(ext) ||
    mime.includes("word") ||
    mime.includes("document")
  ) {
    return "document";
  }
  if (["ppt", "pptx", "odp"].includes(ext) || mime.includes("presentation")) {
    return "presentation";
  }
  if (["zip", "rar", "7z", "tar", "gz", "bz2", "xz"].includes(ext)) {
    return "archive";
  }
  if (["js", "ts", "jsx", "tsx", "py", "rs", "go", "json", "html", "css"].includes(ext)) {
    return "code";
  }
  return "other";
}
