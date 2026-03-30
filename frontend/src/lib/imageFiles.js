const SVG_IMAGE_TYPE = "image/svg+xml";

export const UNSUPPORTED_IMAGE_MESSAGE = "当前暂不支持 SVG 图片，请改用 PNG、JPG、BMP、TIFF 或 WebP。";

export function validateImageFile(file) {
  const contentType = String(file?.type || "").toLowerCase();
  const filename = String(file?.name || "").toLowerCase();

  if (!contentType.startsWith("image/")) {
    return "请选择图片文件。";
  }
  if (contentType === SVG_IMAGE_TYPE || filename.endsWith(".svg")) {
    return UNSUPPORTED_IMAGE_MESSAGE;
  }
  return "";
}
