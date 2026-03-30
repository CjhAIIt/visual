import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { saveBlobAsFile } from "@/lib/download";
import { validateImageFile } from "@/lib/imageFiles";
import { fetchModels, predictImage } from "@/lib/plantApi";
import {
  getDiseaseInfo,
  getVisualizationDownloadName,
  translateLabel,
} from "@/lib/plantPresentation";

const EMPTY_RESULT = null;
const EMPTY_STATISTICS_SESSION = {
  active: false,
  hasFrames: false,
  records: [],
};
const EMPTY_REALTIME_METRICS = {
  mode: "",
  frames: 0,
  startedAt: 0,
  lastRoundtripMs: null,
  averageRoundtripMs: null,
  actualFps: 0,
  lastServerPredictionMs: null,
  lastUpdatedAt: "",
};
const PICTURE_IN_PICTURE_WINDOW = {
  width: 460,
  height: 780,
};
const MIN_REALTIME_LOOP_DELAY_MS = 16;
const DEFAULT_REALTIME_TARGET_FPS = 6;
const DEFAULT_MANUAL_CAPTURE_OPTIONS = {
  maxSide: 1440,
  quality: 0.88,
};
const REALTIME_PROFILE_OPTIONS = [
  {
    id: "speed",
    label: "极速",
    description: "720p · 低延迟",
    maxSide: 720,
    quality: 0.68,
  },
  {
    id: "balanced",
    label: "均衡",
    description: "960p · 推荐",
    maxSide: 960,
    quality: 0.76,
  },
  {
    id: "detail",
    label: "清晰",
    description: "1280p · 更高细节",
    maxSide: 1280,
    quality: 0.84,
  },
];
const DEFAULT_REALTIME_PROFILE_ID = "balanced";
const LIVE_VIDEO_CONSTRAINTS = {
  width: { ideal: 1280 },
  height: { ideal: 720 },
  frameRate: { ideal: 60, max: 60 },
};
const PICTURE_IN_PICTURE_STYLES = `
  :root {
    color-scheme: light;
    font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", sans-serif;
    background:
      radial-gradient(circle at top right, rgba(184, 136, 85, 0.16), transparent 24%),
      linear-gradient(180deg, #141f19 0%, #1e2d24 100%);
    color: #f2ede4;
  }

  * {
    box-sizing: border-box;
  }

  html,
  body {
    margin: 0;
    min-height: 100%;
  }

  body {
    padding: 14px;
    background: inherit;
    color: inherit;
  }

  button,
  input {
    font: inherit;
  }

  .recognition-pip {
    display: grid;
    gap: 12px;
  }

  .recognition-pip__status {
    padding: 12px 13px;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: rgba(242, 237, 228, 0.9);
    line-height: 1.6;
  }

  .recognition-pip__status.is-error {
    background: rgba(173, 75, 58, 0.16);
    color: #ffdacc;
  }

  .recognition-pip__panel,
  .recognition-pip__metric {
    border-radius: 20px;
    border: 1px solid rgba(255, 255, 255, 0.08);
  }

  .recognition-pip__panel {
    display: grid;
    gap: 12px;
    padding: 14px;
    background:
      radial-gradient(circle at top right, rgba(184, 136, 85, 0.12), transparent 28%),
      linear-gradient(180deg, rgba(24, 37, 30, 0.96), rgba(31, 46, 37, 0.94));
  }

  .recognition-pip__panel--hero {
    background:
      radial-gradient(circle at top right, rgba(199, 154, 102, 0.14), transparent 28%),
      linear-gradient(180deg, rgba(28, 41, 33, 0.98), rgba(22, 33, 27, 0.96));
  }

  .recognition-pip__hero,
  .recognition-pip__threshold-head,
  .recognition-pip__section-head,
  .recognition-pip__list-item {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    align-items: center;
  }

  .recognition-pip__hero span,
  .recognition-pip__section-head span,
  .recognition-pip__analysis-meta {
    color: rgba(242, 237, 228, 0.58);
    font-size: 12px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .recognition-pip__hero strong,
  .recognition-pip__section-head strong {
    display: block;
    margin-top: 4px;
    font-size: 17px;
    color: #f3eee6;
  }

  .recognition-pip__close {
    min-height: 36px;
    padding: 0 14px;
    border: 0;
    border-radius: 999px;
    background: linear-gradient(135deg, #c79a66 0%, #ad7744 100%);
    color: #18211c;
    cursor: pointer;
    font-weight: 700;
  }

  .recognition-pip__threshold {
    display: grid;
    gap: 8px;
    padding: 12px;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.06);
  }

  .recognition-pip__threshold strong {
    color: #f4efe6;
  }

  .recognition-pip__threshold input {
    width: 100%;
    margin: 0;
    accent-color: #c79a66;
  }

  .recognition-pip__preview {
    position: relative;
    overflow: hidden;
    border-radius: 18px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    background:
      repeating-linear-gradient(
        90deg,
        rgba(255, 255, 255, 0.04) 0,
        rgba(255, 255, 255, 0.04) 1px,
        transparent 1px,
        transparent 64px
      ),
      linear-gradient(180deg, rgba(12, 19, 15, 0.98), rgba(18, 27, 22, 0.96));
  }

  .recognition-pip__preview img {
    display: block;
    width: 100%;
    height: auto;
    max-height: 250px;
    object-fit: contain;
  }

  .recognition-pip__overlay {
    position: absolute;
    inset: 0;
  }

  .recognition-pip__box {
    position: absolute;
    display: grid;
    align-content: space-between;
    padding: 7px;
    border-radius: 14px;
    border: 2px solid rgba(216, 188, 137, 0.96);
    background: rgba(199, 154, 102, 0.12);
    color: #f7fff3;
  }

  .recognition-pip__box em {
    font-style: normal;
    font-size: 11px;
  }

  .recognition-pip__box strong {
    justify-self: start;
    padding: 2px 7px;
    border-radius: 999px;
    font-size: 11px;
    background: rgba(11, 17, 14, 0.78);
  }

  .recognition-pip__empty,
  .recognition-pip__list-empty {
    padding: 14px;
    border-radius: 16px;
    border: 1px dashed rgba(255, 255, 255, 0.12);
    background: rgba(255, 255, 255, 0.04);
    color: rgba(242, 237, 228, 0.62);
    line-height: 1.7;
  }

  .recognition-pip__metrics {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 10px;
  }

  .recognition-pip__metric {
    display: grid;
    gap: 4px;
    padding: 14px;
    background: rgba(255, 255, 255, 0.05);
  }

  .recognition-pip__metric span,
  .recognition-pip__metric p {
    margin: 0;
    color: rgba(242, 237, 228, 0.58);
  }

  .recognition-pip__metric strong {
    font-size: 17px;
    color: #f4efe6;
    word-break: break-word;
  }

  .recognition-pip__list {
    display: grid;
    gap: 8px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .recognition-pip__list--stacked {
    gap: 10px;
  }

  .recognition-pip__list-item {
    padding: 12px 13px;
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.05);
  }

  .recognition-pip__list-item strong,
  .recognition-pip__list-item span,
  .recognition-pip__analysis p {
    margin: 0;
  }

  .recognition-pip__list-item strong {
    color: #f2ede4;
  }

  .recognition-pip__list-item span,
  .recognition-pip__analysis p {
    color: rgba(242, 237, 228, 0.66);
  }

  .recognition-pip__list-item--stacked {
    align-items: flex-start;
  }

  .recognition-pip__analysis {
    display: grid;
    gap: 10px;
  }

  @media (max-width: 520px) {
    .recognition-pip__metrics {
      grid-template-columns: 1fr;
    }
  }
`;

function formatConfidence(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "--";
  }
  return `${(numeric * 100).toFixed(1)}%`;
}

function formatPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "--";
  }
  return `${numeric.toFixed(1)}%`;
}

function formatAdviceSource(source) {
  switch (source) {
    case "knowledge-base":
      return "知识库缓存";
    case "ai-vision":
      return "多模态大模型";
    case "ai-text":
      return "文本大模型";
    default:
      return "本地规则建议";
  }
}

function formatFps(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return "--";
  }
  return `${numeric.toFixed(numeric >= 10 ? 0 : 1)} FPS`;
}

function formatDurationMs(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) {
    return "--";
  }
  return `${Math.round(numeric)} ms`;
}

function revokeUrl(url) {
  if (url) {
    URL.revokeObjectURL(url);
  }
}

function clamp01(value) {
  return Math.min(1, Math.max(0, Number(value) || 0));
}

async function canvasToBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("当前画面无法导出为图片。"));
        return;
      }
      resolve(blob);
    }, "image/png", 0.94);
  });
}

async function createFileFromCanvas(canvas, filename) {
  return createFileFromCanvasWithOptions(canvas, filename);
}

async function createFileFromCanvasWithOptions(canvas, filename, { quality = 0.92 } = {}) {
  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob((nextBlob) => {
      if (!nextBlob) {
        reject(new Error("当前画面无法导出为图片。"));
        return;
      }
      resolve(nextBlob);
    }, "image/jpeg", quality);
  });
  return new File([blob], filename, { type: "image/jpeg" });
}

function getRealtimeProfile(profileId) {
  return REALTIME_PROFILE_OPTIONS.find((item) => item.id === profileId) || REALTIME_PROFILE_OPTIONS[1];
}

function getLiveSourceLabel(mode) {
  switch (mode) {
    case "camera":
      return "摄像头";
    case "screen":
      return "屏幕共享";
    default:
      return "实时识别";
  }
}

function getLiveReadyStatus(mode) {
  return mode === "screen"
    ? "屏幕共享已连接，可继续手动截取、导出录屏或重新开启实时识别。"
    : "摄像头已连接，可继续手动截取或重新开启实时识别。";
}

function getRealtimeIntervalMs(targetFps) {
  const safeFps = Math.max(0.5, Number(targetFps) || DEFAULT_REALTIME_TARGET_FPS);
  return Math.max(MIN_REALTIME_LOOP_DELAY_MS, Math.round(1000 / safeFps));
}

async function captureVideoFrame(videoElement, filename, { maxSide, quality = 0.92 } = {}) {
  if (!videoElement || !videoElement.videoWidth || !videoElement.videoHeight) {
    throw new Error("当前视频流还没有可捕获的画面。");
  }
  const sourceWidth = videoElement.videoWidth;
  const sourceHeight = videoElement.videoHeight;
  const safeMaxSide = Math.max(320, Number(maxSide) || Math.max(sourceWidth, sourceHeight));
  const scale = Math.min(1, safeMaxSide / Math.max(sourceWidth, sourceHeight));
  const width = Math.max(1, Math.round(sourceWidth * scale));
  const height = Math.max(1, Math.round(sourceHeight * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = scale < 1 ? "high" : "medium";
  context.drawImage(videoElement, 0, 0, canvas.width, canvas.height);
  return createFileFromCanvasWithOptions(canvas, filename, { quality });
}

function getBBoxStyle(bbox, imageMeta) {
  if (!Array.isArray(bbox) || bbox.length !== 4 || !imageMeta.width || !imageMeta.height) {
    return null;
  }
  const [x1, y1, x2, y2] = bbox;
  return {
    left: `${(x1 / imageMeta.width) * 100}%`,
    top: `${(y1 / imageMeta.height) * 100}%`,
    width: `${((x2 - x1) / imageMeta.width) * 100}%`,
    height: `${((y2 - y1) / imageMeta.height) * 100}%`,
  };
}

function getVisualizationLabel(viewMode) {
  return viewMode === "heatmap" ? "热力图" : "检测框";
}

function isPictureInPictureSupported() {
  return typeof window !== "undefined" && Boolean(window.documentPictureInPicture?.requestWindow);
}

function getVisibleItems(items, threshold) {
  if (!Array.isArray(items)) {
    return [];
  }
  const minConfidence = threshold / 100;
  return items.filter((item) => Number(item?.confidence) >= minConfidence);
}

function getAreaSharePercent(item, imageMeta) {
  if (!Array.isArray(item?.bbox) || item.bbox.length !== 4 || !imageMeta.width || !imageMeta.height) {
    return 0;
  }
  const [x1, y1, x2, y2] = item.bbox;
  const boxArea = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const imageArea = imageMeta.width * imageMeta.height || 1;
  return (boxArea / imageArea) * 100;
}

function buildLabelStatistics(items, threshold) {
  const grouped = new Map();
  getVisibleItems(items, threshold)
    .filter((item) => item?.label && item.label !== "No detection")
    .forEach((item) => {
      const existing = grouped.get(item.label) || {
        label: item.label,
        translatedLabel: translateLabel(item.label),
        count: 0,
        totalConfidence: 0,
        maxConfidence: 0,
      };
      existing.count += 1;
      existing.totalConfidence += Number(item.confidence) || 0;
      existing.maxConfidence = Math.max(existing.maxConfidence, Number(item.confidence) || 0);
      grouped.set(item.label, existing);
    });

  return Array.from(grouped.values())
    .map((item) => ({
      ...item,
      averageConfidence: item.count ? item.totalConfidence / item.count : 0,
    }))
    .sort((left, right) => (
      right.count - left.count
      || right.maxConfidence - left.maxConfidence
      || right.averageConfidence - left.averageConfidence
    ));
}

function getStatisticsEmptyMessage(session, sourceItems, threshold) {
  const usableItems = Array.isArray(sourceItems)
    ? sourceItems.filter((item) => item?.label && item.label !== "No detection")
    : [];

  if (session.active || session.hasFrames || session.records.length) {
    if (session.records.length) {
      return `本次实时识别累计结果中，已隐藏低于 ${threshold}% 的标签统计结果。`;
    }
    if (session.hasFrames) {
      return "本次实时识别累计中，当前还没有统计到可用标签。";
    }
    return "开启实时识别后，这里会累计统计标签出现次数。";
  }

  if (usableItems.length) {
    return `当前阈值较高，已隐藏低于 ${threshold}% 的标签统计结果。`;
  }
  return "识别完成后，这里会汇总所有标签的出现次数、最高置信度和平均置信度。";
}

function buildLayerAttentionProfile(item, index) {
  const confidence = clamp01(item.confidence);
  const weight = clamp01(item.weight);
  const rankBoost = clamp01(1 - index * 0.12);
  return [
    {
      title: "第1层",
      name: "纹理感知",
      score: clamp01(0.22 + confidence * 0.32 + rankBoost * 0.16),
    },
    {
      title: "第2层",
      name: "病斑定位",
      score: clamp01(0.28 + confidence * 0.28 + weight * 0.18 + rankBoost * 0.08),
    },
    {
      title: "第3层",
      name: "区域聚合",
      score: clamp01(0.26 + confidence * 0.18 + weight * 0.34 + rankBoost * 0.08),
    },
    {
      title: "第4层",
      name: "判定输出",
      score: clamp01(0.24 + confidence * 0.34 + weight * 0.26 + rankBoost * 0.06),
    },
  ];
}

function buildAttentionItems(detections, threshold) {
  const source = getVisibleItems(detections, threshold)
    .filter((item) => Array.isArray(item?.bbox) && item.bbox.length === 4)
    .sort((left, right) => (Number(right.confidence) || 0) - (Number(left.confidence) || 0));
  const totalConfidence = source.reduce((sum, item) => sum + Math.max(0, Number(item.confidence) || 0), 0) || 1;

  return Array.from({ length: 2 }, (_, index) => {
    const item = source[index];
    if (!item) {
      return {
        id: `placeholder-${index}`,
        rankLabel: `关注 ${index + 1}`,
        title: index === 0 ? "待识别" : "待补充",
        english: index === 0 ? "Waiting for detection" : "Awaiting next focus",
        confidenceText: "0.0%",
        confidenceWidth: "6%",
        footnote: index === 0 ? `当前阈值 ${threshold}%` : "继续识别后会刷新这里",
        layers: [
          { title: "第1层", name: "边缘感知", scoreText: "0.0%", scoreWidth: "6%" },
          { title: "第2层", name: "纹理聚合", scoreText: "0.0%", scoreWidth: "6%" },
          { title: "第3层", name: "病斑定位", scoreText: "0.0%", scoreWidth: "6%" },
          { title: "第4层", name: "类别决策", scoreText: "0.0%", scoreWidth: "6%" },
        ],
        isPlaceholder: true,
      };
    }

    const weight = (Number(item.confidence) || 0) / totalConfidence;
    return {
      id: `${item.label}-${index}`,
      rankLabel: `关注 ${index + 1}`,
      title: translateLabel(item.label),
      english: item.label,
      confidenceText: formatConfidence(item.confidence),
      confidenceWidth: `${Math.max(10, (Number(item.confidence) || 0) * 100)}%`,
      footnote: `检测置信度 ${formatConfidence(item.confidence)} · 权重占比 ${formatPercent(weight * 100)}`,
      layers: buildLayerAttentionProfile({ confidence: item.confidence, weight }, index).map((layer) => ({
        ...layer,
        scoreText: formatPercent(layer.score * 100),
        scoreWidth: `${Math.max(10, layer.score * 100)}%`,
      })),
      isPlaceholder: false,
    };
  });
}

function drawDetectionsOverlay(context, detections, imageMeta, targetWidth, targetHeight) {
  const visibleDetections = Array.isArray(detections) ? detections : [];
  const scaleX = targetWidth / (imageMeta.width || targetWidth || 1);
  const scaleY = targetHeight / (imageMeta.height || targetHeight || 1);
  const fontSize = Math.max(14, Math.round(Math.min(targetWidth, targetHeight) * 0.024));
  const lineWidth = Math.max(2, Math.round(fontSize * 0.16));
  const labelHeight = Math.max(22, Math.round(fontSize * 1.55));
  const labelPaddingX = Math.max(6, Math.round(fontSize * 0.42));

  context.lineWidth = lineWidth;
  context.font = `${fontSize}px "Segoe UI"`;
  context.textBaseline = "alphabetic";

  visibleDetections.forEach((item, index) => {
    if (!Array.isArray(item?.bbox) || item.bbox.length !== 4) {
      return;
    }
    const [x1, y1, x2, y2] = item.bbox;
    const drawX = x1 * scaleX;
    const drawY = y1 * scaleY;
    const drawWidth = (x2 - x1) * scaleX;
    const drawHeight = (y2 - y1) * scaleY;
    const color = index === 0 ? "#f4c95d" : "#79ca8d";
    const text = `${translateLabel(item.label)} ${formatConfidence(item.confidence)}`;

    context.strokeStyle = color;
    context.strokeRect(drawX, drawY, drawWidth, drawHeight);
    const textWidth = context.measureText(text).width;
    const textY = Math.max(labelHeight, drawY - Math.round(fontSize * 0.55));
    context.fillStyle = "rgba(12, 26, 19, 0.84)";
    context.fillRect(drawX, textY - labelHeight, textWidth + labelPaddingX * 2, labelHeight);
    context.fillStyle = "#ffffff";
    context.fillText(text, drawX + labelPaddingX, textY - Math.round(fontSize * 0.18));
  });
}

function drawHeatmapOverlay(context, detections, imageMeta, targetWidth, targetHeight) {
  const visibleDetections = Array.isArray(detections) ? detections : [];
  const scaleX = targetWidth / (imageMeta.width || targetWidth || 1);
  const scaleY = targetHeight / (imageMeta.height || targetHeight || 1);
  const totalConfidence = visibleDetections.reduce((sum, item) => sum + Math.max(Number(item?.confidence) || 0, 0), 0) || 1;
  const badgeFontSize = Math.max(13, Math.round(Math.min(targetWidth, targetHeight) * 0.022));
  const badgePaddingX = Math.max(8, Math.round(badgeFontSize * 0.55));
  const badgeHeight = Math.max(24, Math.round(badgeFontSize * 1.8));
  const strokeWidth = Math.max(2, Math.round(badgeFontSize * 0.12));

  context.fillStyle = "rgba(40, 12, 72, 0.24)";
  context.fillRect(0, 0, targetWidth, targetHeight);

  visibleDetections.forEach((item) => {
    if (!Array.isArray(item?.bbox) || item.bbox.length !== 4) {
      return;
    }
    const [x1, y1, x2, y2] = item.bbox;
    const boxWidth = (x2 - x1) * scaleX;
    const boxHeight = (y2 - y1) * scaleY;
    const centerX = x1 * scaleX + boxWidth / 2;
    const centerY = y1 * scaleY + boxHeight / 2;
    const radius = Math.max(boxWidth, boxHeight) * 0.82;
    const alpha = Math.min(0.95, 0.32 + (Number(item.confidence) || 0) * 0.68);
    const weightPercent = Math.round(((Number(item.confidence) || 0) / totalConfidence) * 100);

    context.save();
    context.globalCompositeOperation = "screen";
    const gradient = context.createRadialGradient(centerX, centerY, radius * 0.08, centerX, centerY, radius);
    gradient.addColorStop(0, `rgba(255, 250, 196, ${Math.min(1, alpha * 1.08)})`);
    gradient.addColorStop(0.24, `rgba(255, 132, 228, ${alpha})`);
    gradient.addColorStop(0.58, `rgba(167, 82, 255, ${alpha * 0.92})`);
    gradient.addColorStop(0.84, `rgba(92, 35, 182, ${alpha * 0.58})`);
    gradient.addColorStop(1, "rgba(28, 6, 64, 0)");
    context.fillStyle = gradient;
    context.fillRect(Math.max(0, centerX - radius), Math.max(0, centerY - radius), radius * 2, radius * 2);
    context.restore();

    context.save();
    context.strokeStyle = `rgba(255, 224, 124, ${Math.min(0.96, 0.38 + (Number(item.confidence) || 0) * 0.5)})`;
    context.lineWidth = Math.max(strokeWidth, strokeWidth + (Number(item.confidence) || 0) * 2.2);
    context.strokeRect(x1 * scaleX, y1 * scaleY, boxWidth, boxHeight);
    context.restore();

    const badgeText = `${weightPercent}%`;
    context.save();
    context.font = `bold ${badgeFontSize}px "Segoe UI"`;
    const badgeWidth = context.measureText(badgeText).width + badgePaddingX * 2;
    const badgeX = Math.max(8, Math.min(targetWidth - badgeWidth - 8, centerX - badgeWidth / 2));
    const badgeY = Math.max(badgeHeight, centerY - radius * 0.36);
    context.fillStyle = "rgba(46, 12, 92, 0.84)";
    context.fillRect(badgeX, badgeY - badgeHeight, badgeWidth, badgeHeight);
    context.strokeStyle = "rgba(255, 226, 140, 0.72)";
    context.lineWidth = Math.max(1, Math.round(badgeFontSize * 0.1));
    context.strokeRect(badgeX, badgeY - badgeHeight, badgeWidth, badgeHeight);
    context.fillStyle = "#fff6c8";
    context.fillText(badgeText, badgeX + badgePaddingX, badgeY - Math.round(badgeFontSize * 0.22));
    context.restore();
  });
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("预览图片载入失败，暂时无法导出。"));
    image.src = src;
  });
}

function preparePictureInPictureWindow(pipWindow) {
  const { document } = pipWindow;
  document.title = "病害识别结果小窗";
  document.documentElement.lang = "zh-CN";
  document.head.replaceChildren();

  const meta = document.createElement("meta");
  meta.setAttribute("charset", "utf-8");
  document.head.appendChild(meta);

  const style = document.createElement("style");
  style.textContent = PICTURE_IN_PICTURE_STYLES;
  document.head.appendChild(style);

  document.body.replaceChildren();
  const container = document.createElement("div");
  document.body.appendChild(container);
  return container;
}

function RecognitionPictureInPicture({
  container,
  previewUrl,
  previewMeta,
  threshold,
  filteredDetections,
  result,
  adviceBundle,
  selectedModel,
  status,
  error,
  liveRecognitionEnabled,
  liveSourceMode,
  realtimeTargetFps,
  realtimeProfile,
  realtimeMetrics,
  onThresholdChange,
  onClose,
}) {
  if (!container) {
    return null;
  }

  const feedback = error || status || "识别结果会实时同步到这里。";
  const adviceItems = Array.isArray(adviceBundle?.advice) ? adviceBundle.advice : [];
  const adviceSource = adviceBundle?.source ? formatAdviceSource(adviceBundle.source) : "--";
  const adviceDetail = String(adviceBundle?.detail || "").trim();
  const visibleModel = result?.model_name || selectedModel || "--";
  const liveSourceLabel = getLiveSourceLabel(liveSourceMode);
  const profileLabel = realtimeProfile ? `${realtimeProfile.label} · ${realtimeProfile.description}` : "--";

  return createPortal(
    <div className="recognition-pip">
      <div className={`recognition-pip__status${error ? " is-error" : ""}`}>
        {feedback}
      </div>

      <section className="recognition-pip__panel recognition-pip__panel--hero">
        <div className="recognition-pip__hero">
          <div>
            <span>Recognition PiP</span>
            <strong>{translateLabel(result?.predicted_class || "待识别")}</strong>
          </div>
          <button type="button" className="recognition-pip__close" onClick={onClose}>
            关闭小窗
          </button>
        </div>

        <label className="recognition-pip__threshold">
          <div className="recognition-pip__threshold-head">
            <span>置信度阈值</span>
            <strong>{threshold}%</strong>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            value={threshold}
            onChange={(event) => onThresholdChange(Number(event.target.value))}
          />
        </label>

        {previewUrl ? (
          <div className="recognition-pip__preview">
            <img src={previewUrl} alt="待识别图片" />
            <div className="recognition-pip__overlay" aria-hidden="true">
              {filteredDetections.map((item, index) => {
                const style = getBBoxStyle(item.bbox, previewMeta);
                if (!style) {
                  return null;
                }
                return (
                  <span key={`${item.label}-${index}`} className="recognition-pip__box" style={style}>
                    <em>{translateLabel(item.label)}</em>
                    <strong>{formatConfidence(item.confidence)}</strong>
                  </span>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="recognition-pip__empty">
            主窗口载入图片后，小窗会自动同步预览和识别结果。
          </div>
        )}
      </section>

      <section className="recognition-pip__metrics">
        <article className="recognition-pip__metric">
          <span>主预测</span>
          <strong>{translateLabel(result?.predicted_class || "--")}</strong>
          <p>置信度 {formatConfidence(result?.confidence)}</p>
        </article>
        <article className="recognition-pip__metric">
          <span>实时来源</span>
          <strong>{liveRecognitionEnabled ? liveSourceLabel : "待开启"}</strong>
          <p>{liveRecognitionEnabled ? `目标 ${formatFps(realtimeTargetFps)}` : "当前为静态查看模式"}</p>
        </article>
        <article className="recognition-pip__metric">
          <span>实时帧率</span>
          <strong>{formatFps(realtimeMetrics?.actualFps)}</strong>
          <p>最近耗时 {formatDurationMs(realtimeMetrics?.lastRoundtripMs)}</p>
        </article>
        <article className="recognition-pip__metric">
          <span>服务端推理</span>
          <strong>{formatDurationMs(result?.prediction_ms ?? realtimeMetrics?.lastServerPredictionMs)}</strong>
          <p>{realtimeMetrics?.lastUpdatedAt ? `更新于 ${realtimeMetrics.lastUpdatedAt}` : "完成识别后显示"}</p>
        </article>
        <article className="recognition-pip__metric">
          <span>当前模型</span>
          <strong>{visibleModel}</strong>
          <p>{liveRecognitionEnabled ? profileLabel : `建议来源 ${adviceSource}`}</p>
        </article>
        <article className="recognition-pip__metric">
          <span>检测框数量</span>
          <strong>{filteredDetections.length}</strong>
          <p>按当前阈值过滤后展示</p>
        </article>
      </section>

      <section className="recognition-pip__panel">
        <div className="recognition-pip__section-head">
          <span>Detections</span>
          <strong>检测明细</strong>
        </div>
        {!filteredDetections.length ? (
          <div className="recognition-pip__list-empty">
            当前阈值下还没有可展示的检测结果。
          </div>
        ) : (
          <ul className="recognition-pip__list">
            {filteredDetections.map((item, index) => (
              <li key={`${item.label}-${index}`} className="recognition-pip__list-item">
                <strong>{translateLabel(item.label)}</strong>
                <span>{formatConfidence(item.confidence)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="recognition-pip__panel">
        <div className="recognition-pip__section-head">
          <span>Analysis</span>
          <strong>智能分析</strong>
        </div>
        {adviceBundle ? (
          <div className="recognition-pip__analysis">
            <p className="recognition-pip__analysis-meta">分析来源：{adviceSource}</p>
            {adviceDetail ? <p className="recognition-pip__analysis-meta">{adviceDetail}</p> : null}
            <p>{adviceBundle.summary}</p>
            <ul className="recognition-pip__list recognition-pip__list--stacked">
              {adviceItems.map((item) => (
                <li key={item} className="recognition-pip__list-item recognition-pip__list-item--stacked">
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="recognition-pip__list-empty">
            完成识别后，这里会同步显示智能分析与处理建议。
          </div>
        )}
      </section>
    </div>,
    container
  );
}

export function RecognitionWorkspace({
  token,
  isAuthenticated,
  initialPayload = null,
  onPredictionReady,
  onOpenAnnotation,
}) {
  const fileInputRef = useRef(null);
  const previewImageRef = useRef(null);
  const heatmapCanvasRef = useRef(null);
  const cameraVideoRef = useRef(null);
  const screenVideoRef = useRef(null);
  const cameraStreamRef = useRef(null);
  const screenStreamRef = useRef(null);
  const cameraReadyRef = useRef(false);
  const screenRecorderRef = useRef(null);
  const screenRecordingChunksRef = useRef([]);
  const screenRecordingUrlRef = useRef("");
  const pipWindowRef = useRef(null);
  const detailSectionRef = useRef(null);
  const mountedRef = useRef(false);
  const previewUrlRef = useRef("");
  const tokenRef = useRef(token);
  const isAuthenticatedRef = useRef(isAuthenticated);
  const selectedModelRef = useRef("");
  const sourceModeRef = useRef("upload");
  const screenReadyRef = useRef(false);
  const realtimeTargetFpsRef = useRef(DEFAULT_REALTIME_TARGET_FPS);
  const realtimeProfileIdRef = useRef(DEFAULT_REALTIME_PROFILE_ID);
  const liveRecognitionTimerRef = useRef(0);
  const liveRecognitionAbortRef = useRef(null);
  const liveRecognitionActiveRef = useRef(false);
  const liveRecognitionModeRef = useRef("");
  const lastPublishedFileRef = useRef(null);

  const [sourceMode, setSourceMode] = useState("upload");
  const [selectedModel, setSelectedModel] = useState("");
  const [availableModels, setAvailableModels] = useState([]);
  const [selectedFile, setSelectedFile] = useState(() => initialPayload?.file || null);
  const [previewUrl, setPreviewUrl] = useState(() => (initialPayload?.file ? URL.createObjectURL(initialPayload.file) : ""));
  const [previewMeta, setPreviewMeta] = useState({ width: 0, height: 0 });
  const [result, setResult] = useState(() => initialPayload?.result || EMPTY_RESULT);
  const [threshold, setThreshold] = useState(10);
  const [visualizationMode, setVisualizationMode] = useState("boxes");
  const [status, setStatus] = useState("上传图片后即可开始识别。");
  const [error, setError] = useState("");
  const [loadingModels, setLoadingModels] = useState(false);
  const [predicting, setPredicting] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);
  const [screenReady, setScreenReady] = useState(false);
  const [liveRecognitionEnabled, setLiveRecognitionEnabled] = useState(false);
  const [liveRecognitionBusy, setLiveRecognitionBusy] = useState(false);
  const [screenRecording, setScreenRecording] = useState(false);
  const [screenRecordingDownload, setScreenRecordingDownload] = useState(null);
  const [statisticsSession, setStatisticsSession] = useState(EMPTY_STATISTICS_SESSION);
  const [realtimeTargetFps, setRealtimeTargetFps] = useState(DEFAULT_REALTIME_TARGET_FPS);
  const [realtimeProfileId, setRealtimeProfileId] = useState(DEFAULT_REALTIME_PROFILE_ID);
  const [realtimeMetrics, setRealtimeMetrics] = useState(EMPTY_REALTIME_METRICS);
  const [pipContainer, setPipContainer] = useState(null);
  const [controlView, setControlView] = useState("source");
  const [detailView, setDetailView] = useState("overview");

  const pictureInPictureSupported = isPictureInPictureSupported();
  const pictureInPictureActive = Boolean(pipContainer && pipWindowRef.current && !pipWindowRef.current.closed);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
      screenStreamRef.current?.getTracks().forEach((track) => track.stop());
      if (screenRecorderRef.current && screenRecorderRef.current.state === "recording") {
        screenRecorderRef.current.stop();
      }
      liveRecognitionAbortRef.current?.abort();
      if (liveRecognitionTimerRef.current) {
        window.clearTimeout(liveRecognitionTimerRef.current);
        liveRecognitionTimerRef.current = 0;
      }
      if (pipWindowRef.current && !pipWindowRef.current.closed) {
        pipWindowRef.current.close();
      }
      pipWindowRef.current = null;
      revokeUrl(previewUrlRef.current);
      revokeUrl(screenRecordingUrlRef.current);
    };
  }, []);

  useEffect(() => {
    previewUrlRef.current = previewUrl;
  }, [previewUrl]);

  useEffect(() => {
    tokenRef.current = token;
  }, [token]);

  useEffect(() => {
    isAuthenticatedRef.current = isAuthenticated;
  }, [isAuthenticated]);

  useEffect(() => {
    selectedModelRef.current = selectedModel;
  }, [selectedModel]);

  useEffect(() => {
    sourceModeRef.current = sourceMode;
  }, [sourceMode]);

  useEffect(() => {
    cameraReadyRef.current = cameraReady;
  }, [cameraReady]);

  useEffect(() => {
    screenReadyRef.current = screenReady;
  }, [screenReady]);

  useEffect(() => {
    realtimeTargetFpsRef.current = realtimeTargetFps;
  }, [realtimeTargetFps]);

  useEffect(() => {
    realtimeProfileIdRef.current = realtimeProfileId;
  }, [realtimeProfileId]);

  useEffect(() => {
    if (!isAuthenticated || !token) {
      setAvailableModels([]);
      setSelectedModel("");
      return;
    }

    let cancelled = false;
    setLoadingModels(true);
    fetchModels(token)
      .then((payload) => {
        if (cancelled) {
          return;
        }
        const items = Array.isArray(payload?.data?.available_model_items) && payload.data.available_model_items.length
          ? payload.data.available_model_items
          : (payload?.data?.available_models || []).map((name) => ({ name }));
        setAvailableModels(items);
        setSelectedModel(payload?.data?.current_model || items[0]?.name || "");
      })
      .catch((nextError) => {
        if (!cancelled) {
          setError(nextError.message || "模型列表获取失败。");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingModels(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, token]);

  useEffect(() => {
    if (!initialPayload?.file) {
      return;
    }
    if (initialPayload.file === lastPublishedFileRef.current) {
      return;
    }
    revokeUrl(previewUrlRef.current);
    const nextPreviewUrl = URL.createObjectURL(initialPayload.file);
    previewUrlRef.current = nextPreviewUrl;
    setSelectedFile(initialPayload.file);
    setPreviewUrl(nextPreviewUrl);
    setResult(initialPayload.result || EMPTY_RESULT);
    setSourceMode("upload");
    setStatisticsSession(EMPTY_STATISTICS_SESSION);
    setRealtimeMetrics(EMPTY_REALTIME_METRICS);
  }, [initialPayload]);

  useEffect(() => {
    if (sourceMode !== "camera") {
      if (liveRecognitionModeRef.current === "camera") {
        stopLiveRecognitionLoop({ keepStatus: true });
      }
      cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
      setCameraReady(false);
      cameraReadyRef.current = false;
    }
    if (sourceMode !== "screen") {
      if (liveRecognitionModeRef.current === "screen") {
        stopLiveRecognitionLoop({ keepStatus: true });
      }
      if (screenRecorderRef.current && screenRecorderRef.current.state === "recording") {
        screenRecorderRef.current.stop();
      }
      screenStreamRef.current?.getTracks().forEach((track) => track.stop());
      screenStreamRef.current = null;
      setScreenReady(false);
      screenReadyRef.current = false;
      setScreenRecording(false);
    }
  }, [sourceMode]);

  useEffect(() => {
    if (isAuthenticated || !liveRecognitionActiveRef.current) {
      return;
    }
    stopLiveRecognitionLoop({ keepStatus: false });
  }, [isAuthenticated]);

  const filteredDetections = useMemo(() => {
    const detections = Array.isArray(result?.detections) ? result.detections : [];
    return getVisibleItems(detections, threshold);
  }, [result, threshold]);

  const visibleTopPredictions = useMemo(() => {
    const predictions = Array.isArray(result?.top_predictions) ? result.top_predictions : [];
    return getVisibleItems(predictions, threshold);
  }, [result, threshold]);

  const labelStatisticsSource = useMemo(() => {
    if (statisticsSession.active || statisticsSession.hasFrames || statisticsSession.records.length) {
      return statisticsSession.records;
    }
    if (Array.isArray(result?.detections) && result.detections.length) {
      return result.detections;
    }
    return Array.isArray(result?.top_predictions) ? result.top_predictions : [];
  }, [result, statisticsSession]);

  const labelStatistics = useMemo(
    () => buildLabelStatistics(labelStatisticsSource, threshold),
    [labelStatisticsSource, threshold]
  );

  const attentionItems = useMemo(
    () => buildAttentionItems(result?.detections || [], threshold),
    [result, threshold]
  );

  const realtimeProfile = useMemo(
    () => getRealtimeProfile(realtimeProfileId),
    [realtimeProfileId]
  );

  const adviceBundle = useMemo(() => {
    if (!result?.predicted_class) {
      return null;
    }
    if (result?.ai_advice) {
      return result.ai_advice;
    }
    const diseaseInfo = getDiseaseInfo(result.predicted_class);
    return {
      disease_label: result.predicted_class,
      summary: diseaseInfo.summary,
      advice: diseaseInfo.advice,
      source: "builtin",
      detail: result?.ai_advice_included === false
        ? "实时模式已切换为轻量预测，当前展示本地病害知识建议；停止实时识别后可手动生成完整大模型分析。"
        : "当前结果未返回大模型说明，已切换为本地病害知识建议。",
    };
  }, [result]);

  const liveOverlayMeta = useMemo(() => {
    const activeVideoElement = sourceMode === "camera" ? cameraVideoRef.current : screenVideoRef.current;
    return {
      width: previewMeta.width || activeVideoElement?.videoWidth || 0,
      height: previewMeta.height || activeVideoElement?.videoHeight || 0,
    };
  }, [cameraReady, previewMeta, result, screenReady, sourceMode]);

  function clearLiveRecognitionTimer() {
    if (liveRecognitionTimerRef.current) {
      window.clearTimeout(liveRecognitionTimerRef.current);
      liveRecognitionTimerRef.current = 0;
    }
  }

  function resetStatisticsSession(active = false) {
    setStatisticsSession({
      active,
      hasFrames: false,
      records: [],
    });
  }

  function stopStatisticsSession() {
    setStatisticsSession((current) => ({ ...current, active: false }));
  }

  function resetRealtimeMetrics(mode = "") {
    setRealtimeMetrics({
      ...EMPTY_REALTIME_METRICS,
      mode,
      startedAt: typeof performance !== "undefined" ? performance.now() : Date.now(),
    });
  }

  function recordRealtimeMetrics(payload, roundtripMs) {
    const now = typeof performance !== "undefined" ? performance.now() : Date.now();
    const activeMode = liveRecognitionModeRef.current;
    const nextServerPredictionMs = Number(payload?.data?.prediction_ms);
    setRealtimeMetrics((current) => {
      const modeChanged = current.mode !== activeMode;
      const previousFrames = modeChanged ? 0 : current.frames;
      const nextFrames = previousFrames + 1;
      const startedAt = modeChanged || !current.startedAt ? now : current.startedAt;
      const averageRoundtripMs = previousFrames
        ? (((Number(current.averageRoundtripMs) || 0) * previousFrames) + roundtripMs) / nextFrames
        : roundtripMs;
      const elapsedSeconds = Math.max((now - startedAt) / 1000, 0.001);
      return {
        mode: activeMode,
        frames: nextFrames,
        startedAt,
        lastRoundtripMs: roundtripMs,
        averageRoundtripMs,
        actualFps: nextFrames / elapsedSeconds,
        lastServerPredictionMs: Number.isFinite(nextServerPredictionMs) ? nextServerPredictionMs : null,
        lastUpdatedAt: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
      };
    });
  }

  function recordStatisticsFrame(items) {
    setStatisticsSession((current) => {
      if (!current.active) {
        return current;
      }
      const nextRecords = Array.isArray(items)
        ? items
          .filter((item) => item?.label && item.label !== "No detection")
          .map((item) => ({
            label: item.label,
            confidence: Number(item.confidence) || 0,
            bbox: Array.isArray(item.bbox) ? item.bbox : null,
          }))
        : [];
      return {
        active: true,
        hasFrames: true,
        records: nextRecords.length ? current.records.concat(nextRecords) : current.records,
      };
    });
  }

  function isLiveSourceReady(mode) {
    if (mode === "camera") {
      return cameraReadyRef.current;
    }
    if (mode === "screen") {
      return screenReadyRef.current;
    }
    return false;
  }

  function getLiveVideoElement(mode) {
    if (mode === "camera") {
      return cameraVideoRef.current;
    }
    if (mode === "screen") {
      return screenVideoRef.current;
    }
    return null;
  }

  function getRealtimeCaptureOptions() {
    const profile = getRealtimeProfile(realtimeProfileIdRef.current);
    return {
      maxSide: profile.maxSide,
      quality: profile.quality,
    };
  }

  function clearScreenRecordingLink() {
    revokeUrl(screenRecordingUrlRef.current);
    screenRecordingUrlRef.current = "";
    if (mountedRef.current) {
      setScreenRecordingDownload(null);
    }
  }

  function syncHeatmapCanvas() {
    const imageElement = previewImageRef.current;
    const canvas = heatmapCanvasRef.current;
    if (!imageElement || !canvas || visualizationMode !== "heatmap") {
      return;
    }
    const rect = imageElement.getBoundingClientRect();
    if (!rect.width || !rect.height) {
      return;
    }
    canvas.width = rect.width;
    canvas.height = rect.height;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    drawHeatmapOverlay(
      context,
      filteredDetections,
      {
        width: previewMeta.width || imageElement.naturalWidth || rect.width,
        height: previewMeta.height || imageElement.naturalHeight || rect.height,
      },
      canvas.width,
      canvas.height
    );
  }

  useEffect(() => {
    if (visualizationMode !== "heatmap" || !previewUrl) {
      const canvas = heatmapCanvasRef.current;
      if (canvas) {
        const context = canvas.getContext("2d");
        context.clearRect(0, 0, canvas.width, canvas.height);
      }
      return;
    }
    const frame = window.requestAnimationFrame(syncHeatmapCanvas);
    window.addEventListener("resize", syncHeatmapCanvas);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", syncHeatmapCanvas);
    };
  }, [filteredDetections, previewMeta, previewUrl, visualizationMode]);

  async function buildVisualizationCanvas(viewMode) {
    const sourceUrl = previewUrlRef.current;
    if (!sourceUrl) {
      throw new Error("当前还没有可导出的识别画面。");
    }
    const image = await loadImage(sourceUrl);
    const width = image.naturalWidth || previewMeta.width || image.width;
    const height = image.naturalHeight || previewMeta.height || image.height;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    context.drawImage(image, 0, 0, width, height);

    const imageSize = {
      width: previewMeta.width || width,
      height: previewMeta.height || height,
    };
    if (viewMode === "heatmap") {
      drawHeatmapOverlay(context, filteredDetections, imageSize, width, height);
    } else {
      drawDetectionsOverlay(context, filteredDetections, imageSize, width, height);
    }
    return canvas;
  }

  async function downloadVisualization(viewMode) {
    try {
      setError("");
      const canvas = await buildVisualizationCanvas(viewMode);
      const blob = await canvasToBlob(canvas);
      const filename = getVisualizationDownloadName(
        selectedFile?.name || result?.filename || `recognition_${Date.now()}.png`,
        viewMode
      );
      saveBlobAsFile(blob, filename);
      setStatus(`${getVisualizationLabel(viewMode)}已导出。`);
    } catch (nextError) {
      setError(nextError.message || "结果导出失败。");
    }
  }

  function stopLiveRecognitionLoop({ keepStatus = false } = {}) {
    const activeMode = liveRecognitionModeRef.current;
    liveRecognitionActiveRef.current = false;
    liveRecognitionModeRef.current = "";
    clearLiveRecognitionTimer();
    liveRecognitionAbortRef.current?.abort();
    liveRecognitionAbortRef.current = null;
    stopStatisticsSession();
    if (mountedRef.current) {
      setLiveRecognitionEnabled(false);
      setLiveRecognitionBusy(false);
      if (!keepStatus && activeMode && isLiveSourceReady(activeMode)) {
        setStatus(getLiveReadyStatus(activeMode));
      }
    }
  }

  function scheduleNextLiveRecognition(delay) {
    if (!liveRecognitionActiveRef.current) {
      return;
    }
    clearLiveRecognitionTimer();
    const nextDelay = Number.isFinite(delay)
      ? Math.max(MIN_REALTIME_LOOP_DELAY_MS, Math.round(delay))
      : getRealtimeIntervalMs(realtimeTargetFpsRef.current);
    liveRecognitionTimerRef.current = window.setTimeout(() => {
      runLiveRecognitionTick();
    }, nextDelay);
  }

  function detachPictureInPictureWindow() {
    pipWindowRef.current = null;
    if (mountedRef.current) {
      setPipContainer(null);
    }
  }

  async function openPictureInPictureWindow({ silent = false } = {}) {
    if (!pictureInPictureSupported) {
      if (!silent) {
        setError("当前浏览器不支持网页画中画结果窗，建议使用新版 Edge 或 Chrome。");
      }
      return false;
    }

    if (pipWindowRef.current && !pipWindowRef.current.closed) {
      pipWindowRef.current.focus();
      return true;
    }

    try {
      const pipWindow = await window.documentPictureInPicture.requestWindow(PICTURE_IN_PICTURE_WINDOW);
      const container = preparePictureInPictureWindow(pipWindow);
      pipWindowRef.current = pipWindow;
      pipWindow.addEventListener("pagehide", detachPictureInPictureWindow, { once: true });
      setPipContainer(container);
      if (!silent) {
        setError("");
      }
      return true;
    } catch (nextError) {
      if (!silent) {
        setError(nextError.message || "画中画结果窗开启失败。");
      }
      return false;
    }
  }

  function closePictureInPictureWindow() {
    const pipWindow = pipWindowRef.current;
    detachPictureInPictureWindow();
    if (pipWindow && !pipWindow.closed) {
      pipWindow.close();
    }
  }

  async function togglePictureInPictureWindow() {
    if (pictureInPictureActive) {
      closePictureInPictureWindow();
      return;
    }
    await openPictureInPictureWindow();
  }

  async function runLiveRecognitionTick() {
    if (!liveRecognitionActiveRef.current) {
      return;
    }

    const activeMode = liveRecognitionModeRef.current;
    if (!isAuthenticatedRef.current || !tokenRef.current || !activeMode || sourceModeRef.current !== activeMode || !isLiveSourceReady(activeMode)) {
      stopLiveRecognitionLoop({ keepStatus: true });
      return;
    }

    const videoElement = getLiveVideoElement(activeMode);
    if (!videoElement || !videoElement.videoWidth || !videoElement.videoHeight) {
      scheduleNextLiveRecognition(220);
      return;
    }

    const tickStartedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
    const controller = new AbortController();
    liveRecognitionAbortRef.current = controller;
    setLiveRecognitionBusy(true);
    try {
      const frameFile = await captureVideoFrame(
        videoElement,
        `${activeMode}_${Date.now()}.jpg`,
        getRealtimeCaptureOptions()
      );
      if (!liveRecognitionActiveRef.current || controller.signal.aborted) {
        return;
      }

      setPreviewFromFile(frameFile, { resetResult: false });
      const payload = await predictImage(
        tokenRef.current,
        frameFile,
        selectedModelRef.current,
        controller.signal,
        {
          includeAiAdvice: false,
          confidenceThreshold: threshold / 100,
        }
      );
      if (!liveRecognitionActiveRef.current || controller.signal.aborted) {
        return;
      }

      const nextResult = payload?.data || EMPTY_RESULT;
      const roundtripMs = (typeof performance !== "undefined" ? performance.now() : Date.now()) - tickStartedAt;
      setResult(nextResult);
      setStatus(
        `${getLiveSourceLabel(activeMode)}实时识别中：${translateLabel(nextResult?.predicted_class || "未识别")}，当前模型 ${
          nextResult?.model_name || selectedModelRef.current || "默认模型"
        }，已切换轻量预测。`
      );
      publishPrediction(frameFile, nextResult);
      recordStatisticsFrame(nextResult?.detections?.length ? nextResult.detections : nextResult?.top_predictions);
      recordRealtimeMetrics(payload, roundtripMs);
      setError("");
      scheduleNextLiveRecognition(Math.max(MIN_REALTIME_LOOP_DELAY_MS, getRealtimeIntervalMs(realtimeTargetFpsRef.current) - roundtripMs));
    } catch (nextError) {
      if (controller.signal.aborted) {
        return;
      }
      setError(nextError.message || `${getLiveSourceLabel(activeMode)}实时识别失败。`);
      setStatus(`${getLiveSourceLabel(activeMode)}实时识别已暂停，请检查网络、模型或服务器负载后重试。`);
      stopLiveRecognitionLoop({ keepStatus: true });
    } finally {
      if (liveRecognitionAbortRef.current === controller) {
        liveRecognitionAbortRef.current = null;
      }
      if (mountedRef.current) {
        setLiveRecognitionBusy(false);
      }
    }
  }

  async function startLiveRecognitionLoop({ autoOpenPictureInPicture = false } = {}) {
    const activeMode = sourceModeRef.current;
    const sourceLabel = getLiveSourceLabel(activeMode);
    if (!isAuthenticatedRef.current || !tokenRef.current) {
      setError(`请先登录后再使用${sourceLabel}实时识别。`);
      return;
    }
    if (activeMode !== "camera" && activeMode !== "screen") {
      setError("请先选择摄像头或屏幕采集，再开启实时识别。");
      return;
    }
    if (!isLiveSourceReady(activeMode)) {
      setError(activeMode === "screen" ? "请先共享屏幕，再开启实时识别。" : "请先连接摄像头，再开启实时识别。");
      return;
    }
    if (liveRecognitionActiveRef.current) {
      return;
    }

    resetStatisticsSession(true);
    resetRealtimeMetrics(activeMode);
    liveRecognitionActiveRef.current = true;
    liveRecognitionModeRef.current = activeMode;
    setLiveRecognitionEnabled(true);
    setLiveRecognitionBusy(true);
    setError("");
    setStatus(`${sourceLabel}已连接，正在实时识别当前画面，并优先保证刷新速度...`);
    if (autoOpenPictureInPicture) {
      await openPictureInPictureWindow({ silent: true });
    }
    await runLiveRecognitionTick();
  }

  function stopScreenRecording() {
    if (screenRecorderRef.current && screenRecorderRef.current.state === "recording") {
      screenRecorderRef.current.stop();
    }
  }

  function setPreviewFromFile(file, { resetResult = true, nextStatus = "" } = {}) {
    revokeUrl(previewUrlRef.current);
    const nextPreviewUrl = URL.createObjectURL(file);
    previewUrlRef.current = nextPreviewUrl;
    setSelectedFile(file);
    setPreviewUrl(nextPreviewUrl);
    if (resetResult) {
      setPreviewMeta({ width: 0, height: 0 });
      setResult(EMPTY_RESULT);
      setVisualizationMode("boxes");
      setStatisticsSession(EMPTY_STATISTICS_SESSION);
      setRealtimeMetrics(EMPTY_REALTIME_METRICS);
    }
    setError("");
    if (nextStatus) {
      setStatus(nextStatus);
    }
  }

  function replacePreviewWithFile(file, nextStatus) {
    setPreviewFromFile(file, { resetResult: true, nextStatus });
  }

  function publishPrediction(file, nextResult) {
    lastPublishedFileRef.current = file;
    startTransition(() => {
      onPredictionReady?.({
        file,
        result: nextResult,
      });
    });
  }

  function handleFileChange(event) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    const validationError = validateImageFile(file);
    if (validationError) {
      setError(validationError);
      event.target.value = "";
      return;
    }
    replacePreviewWithFile(file, `已载入图片 ${file.name}，可以直接开始识别。`);
    setControlView("run");
  }

  async function handlePredict() {
    if (!isAuthenticated || !token) {
      setError("请先登录后再开始识别。");
      return;
    }
    if (!selectedFile) {
      setError("请先选择或采集一张图片。");
      return;
    }
    if (liveRecognitionEnabled) {
      setError("实时识别运行中，请先停止实时识别，再对当前画面执行完整分析。");
      return;
    }

    setPredicting(true);
    setError("");
    setStatisticsSession(EMPTY_STATISTICS_SESSION);
    setStatus("正在上传图片并请求识别结果...");
    try {
      const payload = await predictImage(token, selectedFile, selectedModel, undefined, {
        includeAiAdvice: true,
        confidenceThreshold: threshold / 100,
      });
      const nextResult = payload?.data || EMPTY_RESULT;
      setResult(nextResult);
      setStatus(`识别完成：${translateLabel(nextResult?.predicted_class || "未识别")}，当前模型 ${nextResult?.model_name || selectedModel || "默认模型"}，已生成结果分析。`);
      publishPrediction(selectedFile, nextResult);
    } catch (nextError) {
      setError(nextError.message || "识别失败。");
    } finally {
      setPredicting(false);
    }
  }

  async function startCamera() {
    try {
      setError("");
      stopLiveRecognitionLoop({ keepStatus: true });
      const stream = await navigator.mediaDevices.getUserMedia({ video: LIVE_VIDEO_CONSTRAINTS, audio: false });
      cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = stream;
      const [track] = stream.getVideoTracks();
      if (track) {
        if ("contentHint" in track) {
          track.contentHint = "motion";
        }
        track.addEventListener("ended", () => {
          stopLiveRecognitionLoop({ keepStatus: true });
          setCameraReady(false);
          cameraReadyRef.current = false;
          cameraStreamRef.current = null;
          setStatus("摄像头连接已结束。");
        }, { once: true });
      }
      if (cameraVideoRef.current) {
        cameraVideoRef.current.srcObject = stream;
        await cameraVideoRef.current.play().catch(() => {});
      }
      setCameraReady(true);
      cameraReadyRef.current = true;
      if (!isAuthenticated || !token) {
        setStatus("摄像头已连接，登录后可自动开启实时识别和画中画。");
        return;
      }
      setStatus("摄像头已连接，正在尝试开启实时识别与画中画。");
      await startLiveRecognitionLoop({ autoOpenPictureInPicture: true });
    } catch (nextError) {
      setError(nextError.message || "摄像头初始化失败。");
    }
  }

  async function startScreen() {
    try {
      setError("");
      stopLiveRecognitionLoop({ keepStatus: true });
      stopScreenRecording();
      clearScreenRecordingLink();
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: { ideal: 60, max: 60 } },
        audio: false,
      });
      screenStreamRef.current?.getTracks().forEach((track) => track.stop());
      screenStreamRef.current = stream;
      const [track] = stream.getVideoTracks();
      if (track) {
        if ("contentHint" in track) {
          track.contentHint = "motion";
        }
        track.addEventListener("ended", () => {
          stopLiveRecognitionLoop({ keepStatus: true });
          stopScreenRecording();
          setScreenReady(false);
          screenReadyRef.current = false;
          screenStreamRef.current = null;
          setStatus("屏幕共享已结束。");
        }, { once: true });
      }
      if (screenVideoRef.current) {
        screenVideoRef.current.srcObject = stream;
        await screenVideoRef.current.play().catch(() => {});
      }
      setScreenReady(true);
      screenReadyRef.current = true;
      if (!isAuthenticated || !token) {
        setStatus("屏幕共享已连接，登录后可自动开启实时识别、画中画和录屏下载。");
        return;
      }
      setStatus("屏幕共享已连接，正在尝试开启实时识别与画中画。");
      await startLiveRecognitionLoop({ autoOpenPictureInPicture: true });
    } catch (nextError) {
      setError(nextError.message || "屏幕共享初始化失败。");
    }
  }

  async function captureFromVideo(mode) {
    try {
      const targetVideo = mode === "camera" ? cameraVideoRef.current : screenVideoRef.current;
      const file = await captureVideoFrame(targetVideo, `${mode}_${Date.now()}.jpg`, DEFAULT_MANUAL_CAPTURE_OPTIONS);
      replacePreviewWithFile(file, mode === "camera" ? "已截取摄像头画面，可以开始识别。" : "已截取屏幕画面，可以开始识别。");
      setSourceMode("upload");
    } catch (nextError) {
      setError(nextError.message || "画面截取失败。");
    }
  }

  function startScreenRecording() {
    if (!screenStreamRef.current) {
      setError("请先共享屏幕，再开始录屏。");
      return;
    }
    if (typeof MediaRecorder === "undefined") {
      setError("当前浏览器不支持 MediaRecorder，无法录屏。");
      return;
    }

    clearScreenRecordingLink();
    screenRecordingChunksRef.current = [];

    let recorder = null;
    try {
      recorder = new MediaRecorder(screenStreamRef.current, { mimeType: "video/webm;codecs=vp9,opus" });
    } catch {
      try {
        recorder = new MediaRecorder(screenStreamRef.current, { mimeType: "video/webm" });
      } catch (nextError) {
        setError(nextError.message || "录屏初始化失败。");
        return;
      }
    }

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data && event.data.size > 0) {
        screenRecordingChunksRef.current.push(event.data);
      }
    });

    recorder.addEventListener("stop", () => {
      const chunks = screenRecordingChunksRef.current;
      screenRecorderRef.current = null;
      if (!mountedRef.current) {
        return;
      }
      setScreenRecording(false);
      if (!chunks.length) {
        setStatus("录屏已停止，但没有生成可下载的数据。");
        return;
      }
      const blob = new Blob(chunks, { type: recorder.mimeType || "video/webm" });
      const url = URL.createObjectURL(blob);
      screenRecordingUrlRef.current = url;
      const name = `screen_record_${Date.now()}.webm`;
      setScreenRecordingDownload({ url, name });
      setStatus("录屏已停止，已生成下载链接。");
    }, { once: true });

    recorder.start();
    screenRecorderRef.current = recorder;
    setScreenRecording(true);
    setError("");
    setStatus("录屏已开始，可继续实时识别或随时截取当前画面。");
  }

  const primaryPrediction = result?.predicted_class
    ? {
      translatedLabel: translateLabel(result.predicted_class),
      rawLabel: result.predicted_class,
      confidence: result.confidence,
    }
    : null;

  const resultFilename = result?.filename || selectedFile?.name || "--";
  const hasRecognitionResult = Boolean(
    primaryPrediction || filteredDetections.length || visibleTopPredictions.length || adviceBundle
  );
  const hasPreparedInput = sourceMode === "upload"
    ? Boolean(selectedFile)
    : sourceMode === "camera"
      ? cameraReady
      : screenReady;
  const hasFrameForManualRun = Boolean(selectedFile);
  const sourceModeLabel = sourceMode === "upload" ? "上传图片" : sourceMode === "camera" ? "摄像头" : "屏幕采集";
  const captureStatusText = sourceMode === "upload"
    ? (selectedFile?.name || "还没有选择图片")
    : sourceMode === "camera"
      ? (cameraReady ? "摄像头已连接，可直接截帧或开实时识别" : "还没有连接摄像头")
      : (screenReady ? "屏幕已共享，可直接截帧或开实时识别" : "还没有共享屏幕");
  const runStatusText = hasRecognitionResult ? "已有结果" : hasFrameForManualRun ? "可以执行" : "先准备画面";
  const controlSteps = [
    { id: "source", label: "来源", summary: sourceModeLabel },
    { id: "capture", label: "准备", summary: hasPreparedInput ? "已就绪" : "待准备" },
    { id: "run", label: "执行", summary: runStatusText },
  ];
  const detailTabs = [
    {
      id: "overview",
      label: "概览",
      summary: `${visibleTopPredictions.length} 个候选`,
    },
    {
      id: "detections",
      label: "检测",
      summary: `${filteredDetections.length} 条明细`,
    },
    {
      id: "attention",
      label: "关注",
      summary: filteredDetections.length ? `${Math.min(filteredDetections.length, 2)} 张快照` : "待生成",
    },
    {
      id: "analysis",
      label: "分析",
      summary: adviceBundle ? "已生成建议" : "等待结果",
    },
  ];

  function handleDetailViewChange(nextView) {
    setDetailView(nextView);
    window.requestAnimationFrame(() => {
      detailSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  return (
    <section className="native-workspace native-workspace--recognition">
      <div className="native-workspace__panel native-workspace__panel--controls">
        <div className="native-workspace__section-head">
          <p className="workspace__section-label">Recognition</p>
          <h3>病害识别</h3>
          <p>右侧只保留来源、准备和执行三步，不再把采集、参数和说明堆成一列。</p>
        </div>

        <div className="recognition-control-summary">
          <article className="recognition-control-summary__card">
            <span>输入源</span>
            <strong>{sourceModeLabel}</strong>
            <p>{captureStatusText}</p>
          </article>
          <article className="recognition-control-summary__card">
            <span>当前模型</span>
            <strong>{selectedModel || "--"}</strong>
            <p>{loadingModels ? "正在加载模型" : isAuthenticated ? "已连接推理服务" : "登录后选择模型"}</p>
          </article>
        </div>

        <div className="recognition-control-nav" role="tablist" aria-label="识别控制步骤">
          {controlSteps.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={controlView === item.id}
              className={`recognition-control-nav__item${controlView === item.id ? " is-active" : ""}`}
              onClick={() => setControlView(item.id)}
            >
              <span>{item.label}</span>
              <strong>{item.summary}</strong>
            </button>
          ))}
        </div>

        {sourceMode === "upload" ? (
          <input
            ref={fileInputRef}
            className="native-file-input recognition-file-input"
            type="file"
            accept="image/*"
            onChange={handleFileChange}
          />
        ) : null}

        {controlView === "source" ? (
          <section className="recognition-control-card">
            <div className="recognition-control-card__head">
              <div>
                <p className="workspace__section-label">Step 01</p>
                <h4>选择来源和模型</h4>
              </div>
              <button type="button" className="secondary" onClick={() => setControlView("capture")}>
                下一步
              </button>
            </div>

            <div className="native-tablist" role="tablist" aria-label="识别输入来源">
              {[
                { id: "upload", label: "上传图片" },
                { id: "camera", label: "摄像头" },
                { id: "screen", label: "屏幕采集" },
              ].map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`native-tablist__item${sourceMode === item.id ? " is-active" : ""}`}
                  onClick={() => {
                    setSourceMode(item.id);
                    setControlView("capture");
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <label className="native-field">
              <span>推理模型</span>
              <select value={selectedModel} onChange={(event) => setSelectedModel(event.target.value)} disabled={!isAuthenticated || loadingModels}>
                {!availableModels.length ? <option value="">{loadingModels ? "正在加载模型..." : "暂无可用模型"}</option> : null}
                {availableModels.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          </section>
        ) : null}

        {controlView === "capture" ? (
          <section className="recognition-control-card">
            <div className="recognition-control-card__head">
              <div>
                <p className="workspace__section-label">Step 02</p>
                <h4>准备识别画面</h4>
              </div>
              <button type="button" className="secondary" onClick={() => setControlView("run")} disabled={!hasPreparedInput}>
                去执行
              </button>
            </div>

            {sourceMode === "upload" ? (
              <>
                <div className="recognition-control-card__surface">
                  <strong>{selectedFile ? selectedFile.name : "还没有选择图片"}</strong>
                  <p>支持 JPEG、PNG、WebP。</p>
                </div>
                <button type="button" className="secondary" onClick={() => fileInputRef.current?.click()}>
                  选择图片
                </button>
              </>
            ) : null}

            {sourceMode === "camera" ? (
              <>
                <div className="recognition-hidden-media" aria-hidden="true">
                  <video ref={cameraVideoRef} autoPlay muted playsInline />
                </div>
                <div className="recognition-control-card__surface">
                  <strong>{cameraReady ? "摄像头已连接" : "等待连接摄像头"}</strong>
                  <p>实时结果直接回到左侧预览区，不再在右侧重复显示。</p>
                </div>
                <div className="native-inline-actions native-inline-actions--triple">
                  <button type="button" className="secondary" onClick={startCamera}>
                    {cameraReady ? "重新连接" : "连接摄像头"}
                  </button>
                  <button
                    type="button"
                    className="primary"
                    onClick={() => {
                      if (liveRecognitionEnabled) {
                        stopLiveRecognitionLoop({ keepStatus: false });
                        return;
                      }
                      startLiveRecognitionLoop({ autoOpenPictureInPicture: true });
                    }}
                    disabled={!cameraReady || (!isAuthenticated && !liveRecognitionEnabled)}
                  >
                    {liveRecognitionEnabled ? "停止实时识别" : liveRecognitionBusy ? "启动中..." : "开启实时识别"}
                  </button>
                  <button type="button" className="primary" onClick={() => captureFromVideo("camera")} disabled={!cameraReady}>
                    截取当前画面
                  </button>
                </div>
              </>
            ) : null}

            {sourceMode === "screen" ? (
              <>
                <div className="recognition-hidden-media" aria-hidden="true">
                  <video ref={screenVideoRef} autoPlay muted playsInline />
                </div>
                <div className="recognition-control-card__surface">
                  <strong>{screenReady ? "屏幕已共享" : "等待共享屏幕"}</strong>
                  <p>录屏和截帧都在这一步完成，左侧只负责展示结果。</p>
                </div>
                <div className="native-inline-actions native-inline-actions--triple">
                  <button type="button" className="secondary" onClick={startScreen}>
                    {screenReady ? "重新共享" : "共享屏幕"}
                  </button>
                  <button
                    type="button"
                    className="primary"
                    onClick={() => {
                      if (liveRecognitionEnabled) {
                        stopLiveRecognitionLoop({ keepStatus: false });
                        return;
                      }
                      startLiveRecognitionLoop({ autoOpenPictureInPicture: true });
                    }}
                    disabled={!screenReady || (!isAuthenticated && !liveRecognitionEnabled)}
                  >
                    {liveRecognitionEnabled ? "停止实时识别" : liveRecognitionBusy ? "启动中..." : "开启实时识别"}
                  </button>
                  <button type="button" className="primary" onClick={() => captureFromVideo("screen")} disabled={!screenReady}>
                    截取当前画面
                  </button>
                </div>
                <div className="native-inline-actions">
                  <button
                    type="button"
                    className={screenRecording ? "primary" : "secondary"}
                    onClick={() => {
                      if (screenRecording) {
                        stopScreenRecording();
                        return;
                      }
                      startScreenRecording();
                    }}
                    disabled={!screenReady}
                  >
                    {screenRecording ? "停止录屏" : "开始录屏"}
                  </button>
                  {screenRecordingDownload ? (
                    <a className="native-link" href={screenRecordingDownload.url} download={screenRecordingDownload.name}>
                      下载录屏文件
                    </a>
                  ) : null}
                </div>
              </>
            ) : null}
          </section>
        ) : null}

        {controlView === "run" ? (
          <section className="recognition-control-card">
            <div className="recognition-control-card__head">
              <div>
                <p className="workspace__section-label">Step 03</p>
                <h4>执行与导出</h4>
              </div>
              <button type="button" className="secondary" onClick={() => setControlView("capture")}>
                返回准备
              </button>
            </div>

            {!hasFrameForManualRun && !hasRecognitionResult ? (
              <div className="recognition-control-card__surface">
                <strong>{sourceMode === "upload" ? "先选一张图片" : "先截取一帧画面"}</strong>
                <p>{sourceMode === "upload" ? "图片准备好之后，再回来执行完整识别。" : "实时识别可以先开，但完整分析需要截取当前画面。"}</p>
              </div>
            ) : (
              <>
                <div className="native-inline-actions native-inline-actions--triple">
                  <button
                    type="button"
                    className="primary"
                    onClick={handlePredict}
                    disabled={predicting || liveRecognitionEnabled || !selectedFile || !isAuthenticated}
                  >
                    {predicting ? "识别中..." : "开始识别"}
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      if (result) {
                        onOpenAnnotation?.();
                      }
                    }}
                    disabled={!result}
                  >
                    送去标注
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={togglePictureInPictureWindow}
                    disabled={!pictureInPictureSupported}
                    title={pictureInPictureSupported ? "在独立悬浮窗中查看识别结果" : "当前浏览器不支持网页画中画结果窗"}
                  >
                    {pictureInPictureActive ? "关闭画中画" : "打开画中画"}
                  </button>
                </div>

                <details className="recognition-advanced">
                  <summary>高级设置</summary>
                  {sourceMode === "camera" || sourceMode === "screen" ? (
                    <div className="recognition-advanced__grid">
                      <label className="native-field">
                        <span>实时采样模式</span>
                        <select value={realtimeProfileId} onChange={(event) => setRealtimeProfileId(event.target.value)}>
                          {REALTIME_PROFILE_OPTIONS.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.label} · {item.description}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="native-field">
                        <span>目标实时速度 {formatFps(realtimeTargetFps)}</span>
                        <input
                          type="range"
                          min="1"
                          max="60"
                          step="0.5"
                          value={realtimeTargetFps}
                          onChange={(event) => setRealtimeTargetFps(Number(event.target.value))}
                        />
                      </label>
                      <div className="native-inline-actions">
                        <span className="native-pill native-pill--accent">目标 {formatFps(realtimeTargetFps)}</span>
                        <span className="native-pill native-pill--warm">实际 {formatFps(realtimeMetrics.actualFps)}</span>
                        <span className="native-pill native-pill--neutral">最近 {formatDurationMs(realtimeMetrics.lastRoundtripMs)}</span>
                        <span className="native-pill native-pill--neutral">推理 {formatDurationMs(result?.prediction_ms ?? realtimeMetrics.lastServerPredictionMs)}</span>
                      </div>
                    </div>
                  ) : null}

                  <label className="native-field">
                    <span>推理置信度阈值 {threshold}%</span>
                    <input type="range" min="0" max="100" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} />
                  </label>
                </details>
              </>
            )}
          </section>
        ) : null}

        <div className="native-feedback">
          <p>{status}</p>
          {error ? <strong>{error}</strong> : null}
        </div>
      </div>

        <div className="native-workspace__panel native-workspace__panel--canvas">
          <div className="native-workspace__section-head">
            <p className="workspace__section-label">Preview</p>
            <h3>识别结果</h3>
          </div>

        <div className="recognition-stage__toolbar">
          <div className="recognition-stage__modes" role="tablist" aria-label="识别结果视图">
            <button
              type="button"
              className={`recognition-stage__mode${visualizationMode === "boxes" ? " is-active" : ""}`}
              onClick={() => setVisualizationMode("boxes")}
            >
              检测框
            </button>
            <button
              type="button"
              className={`recognition-stage__mode${visualizationMode === "heatmap" ? " is-active" : ""}`}
              onClick={() => setVisualizationMode("heatmap")}
            >
              热力图
            </button>
          </div>
          <div className="recognition-stage__actions">
            <button type="button" className="secondary" onClick={() => downloadVisualization("boxes")} disabled={!previewUrl}>
              下载标框图
            </button>
            <button type="button" className="secondary" onClick={() => downloadVisualization("heatmap")} disabled={!previewUrl}>
              下载热力图
            </button>
          </div>
        </div>

        <div className={`recognition-stage${visualizationMode === "heatmap" ? " is-heatmap" : ""}${!previewUrl ? " recognition-stage--empty" : ""}`}>
          {previewUrl ? (
            <div className="recognition-stage__media">
              <img
                ref={previewImageRef}
                src={previewUrl}
                alt="待识别图片"
                onLoad={(event) => {
                  setPreviewMeta({
                    width: event.currentTarget.naturalWidth,
                    height: event.currentTarget.naturalHeight,
                  });
                  if (visualizationMode === "heatmap") {
                    window.requestAnimationFrame(syncHeatmapCanvas);
                  }
                }}
              />
              <canvas
                ref={heatmapCanvasRef}
                className={`recognition-stage__heatmap${visualizationMode === "heatmap" ? " is-visible" : ""}`}
                aria-hidden="true"
              />
              <div className={`recognition-stage__overlay${visualizationMode === "boxes" ? " is-visible" : " is-hidden"}`} aria-hidden="true">
                {filteredDetections.map((item, index) => {
                  const style = getBBoxStyle(item.bbox, previewMeta);
                  if (!style) {
                    return null;
                  }
                  return (
                    <span key={`${item.label}-${index}`} className="recognition-box" style={style}>
                      <em>{translateLabel(item.label)}</em>
                      <strong>{formatConfidence(item.confidence)}</strong>
                    </span>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="native-empty">
              <strong>还没有待识别图片</strong>
              <p>上传图片、连接摄像头或共享屏幕后，右侧会显示当前识别画面。</p>
            </div>
          )}
        </div>

        {hasRecognitionResult ? (
          <>
            <div className="recognition-result-grid">
              <article className="recognition-result-card recognition-result-card--hero">
                <span>主预测</span>
                <strong>{primaryPrediction?.translatedLabel || "--"}</strong>
                <p>{primaryPrediction ? `模型标签 ${primaryPrediction.rawLabel}` : "完成识别后显示主预测"}</p>
              </article>
              <article className="recognition-result-card">
                <span>主置信度</span>
                <strong>{formatConfidence(primaryPrediction?.confidence)}</strong>
                <p>基于当前主预测输出</p>
              </article>
              <article className="recognition-result-card">
                <span>检测框数量</span>
                <strong>{filteredDetections.length}</strong>
                <p>按当前阈值过滤后展示</p>
              </article>
              <article className="recognition-result-card">
                <span>当前模型</span>
                <strong>{result?.model_name || selectedModel || "--"}</strong>
                <p>结果文件 {resultFilename}</p>
              </article>
              <article className="recognition-result-card">
                <span>服务端推理</span>
                <strong>{formatDurationMs(result?.prediction_ms)}</strong>
                <p>{result?.ai_advice_included === false ? "当前为轻量实时模式" : "完整识别会额外生成 AI 分析"}</p>
              </article>
            </div>

            <section ref={detailSectionRef} className="recognition-detail-shell">
              <div className="recognition-detail-nav" role="tablist" aria-label="识别详情跳转">
                {detailTabs.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    role="tab"
                    aria-selected={detailView === item.id}
                    className={`recognition-detail-nav__item${detailView === item.id ? " is-active" : ""}`}
                    onClick={() => handleDetailViewChange(item.id)}
                  >
                    <span>{item.label}</span>
                    <strong>{item.summary}</strong>
                  </button>
                ))}
              </div>

              <div className="recognition-dual-grid">
                <section className="asset-collection recognition-collection">
                  <div className="asset-collection__head">
                    <div>
                      <p className="workspace__section-label">Candidates</p>
                      <h3>候选结果</h3>
                    </div>
                    <span className="native-pill native-pill--accent">{visibleTopPredictions.length} 个可见候选</span>
                  </div>
                  {!result ? (
                    <div className="native-empty native-empty--compact">
                      <p>识别完成后，这里会列出候选类别与置信度。</p>
                    </div>
                  ) : !visibleTopPredictions.length ? (
                    <div className="native-empty native-empty--compact">
                      <p>当前阈值下暂无可展示候选结果，可尝试降低阈值查看。</p>
                    </div>
                  ) : (
                    <ul className="native-list native-list--stacked">
                      {visibleTopPredictions.map((item, index) => (
                        <li key={`${item.label}-${index}`} className="native-list__item native-list__item--stacked recognition-list__item">
                          <strong>{translateLabel(item.label)}</strong>
                          <span>{formatConfidence(item.confidence)}</span>
                          <p>模型标签 {item.label}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section className="asset-collection recognition-collection">
                  <div className="asset-collection__head">
                    <div>
                      <p className="workspace__section-label">Statistics</p>
                      <h3>标签统计</h3>
                    </div>
                    <span className={`native-pill ${statisticsSession.active ? "native-pill--warm" : "native-pill--neutral"}`}>
                      {statisticsSession.active ? "实时累计中" : "当前结果"}
                    </span>
                  </div>
                  {!labelStatistics.length ? (
                    <div className="native-empty native-empty--compact">
                      <p>{getStatisticsEmptyMessage(statisticsSession, labelStatisticsSource, threshold)}</p>
                    </div>
                  ) : (
                    <ul className="native-list native-list--stacked">
                      {labelStatistics.map((item) => (
                        <li key={item.label} className="native-list__item native-list__item--stacked recognition-list__item">
                          <strong>{item.translatedLabel}</strong>
                          <span>{item.count} 个目标</span>
                          <p>
                            最高 {formatConfidence(item.maxConfidence)} · 平均 {formatConfidence(item.averageConfidence)}
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>

              <div className="recognition-list">
                <div className="native-workspace__section-head">
                  <p className="workspace__section-label">Detections</p>
                  <h3>检测明细</h3>
                </div>
                {!filteredDetections.length ? (
                  <div className="native-empty native-empty--compact">
                    <p>识别完成后，这里会列出当前阈值下的检测结果。</p>
                  </div>
                ) : (
                  <ul className="native-list native-list--stacked">
                    {filteredDetections.map((item, index) => (
                      <li key={`${item.label}-${index}`} className="native-list__item native-list__item--stacked recognition-list__item">
                        <strong>{translateLabel(item.label)}</strong>
                        <span>{formatConfidence(item.confidence)}</span>
                        <p>
                          模型标签 {item.label}
                          {Array.isArray(item.bbox) && item.bbox.length === 4 ? ` · 关注面积 ${formatPercent(getAreaSharePercent(item, previewMeta))}` : ""}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="recognition-attention">
                <div className="native-workspace__section-head">
                  <p className="workspace__section-label">Attention</p>
                  <h3>关注度快照</h3>
                </div>
                <div className="recognition-attention__grid">
                  {attentionItems.map((item) => (
                    <article
                      key={item.id}
                      className={`recognition-attention__card${item.isPlaceholder ? " is-placeholder" : ""}`}
                    >
                      <div className="recognition-attention__top">
                        <span>{item.rankLabel}</span>
                        <strong>{item.confidenceText}</strong>
                      </div>
                      <div className="recognition-attention__title">
                        <h4>{item.title}</h4>
                        <p>{item.english}</p>
                      </div>
                      <div className="recognition-attention__track">
                        <span style={{ width: item.confidenceWidth }} />
                      </div>
                      <p className="recognition-attention__foot">{item.footnote}</p>
                      <div className="recognition-attention__layers">
                        {item.layers.map((layer) => (
                          <div key={`${item.id}-${layer.title}`} className="recognition-attention__layer">
                            <div className="recognition-attention__layer-head">
                              <span>{layer.title} · {layer.name}</span>
                              <strong>{layer.scoreText}</strong>
                            </div>
                            <div className="recognition-attention__layer-track">
                              <span style={{ width: layer.scoreWidth }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              </div>

              <div className="recognition-advice">
                <div className="native-workspace__section-head">
                  <p className="workspace__section-label">Analysis</p>
                  <h3>智能分析</h3>
                </div>
                {adviceBundle ? (
                  <>
                    <p className="recognition-advice__meta">分析来源：{formatAdviceSource(adviceBundle.source)}</p>
                    {adviceBundle.detail ? <p className="recognition-advice__meta">{adviceBundle.detail}</p> : null}
                    <p>{adviceBundle.summary}</p>
                    <ul className="native-list native-list--stacked">
                      {(adviceBundle.advice || []).map((item) => (
                        <li key={item} className="native-list__item native-list__item--stacked">
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <div className="native-empty native-empty--compact">
                    <p>完成识别后，这里会生成病害分析与处理建议。</p>
                  </div>
                )}
              </div>
            </section>
          </>
        ) : null}
      </div>

      <RecognitionPictureInPicture
        container={pipContainer}
        previewUrl={previewUrl}
        previewMeta={previewMeta}
        threshold={threshold}
        filteredDetections={filteredDetections}
        result={result}
        adviceBundle={adviceBundle}
        selectedModel={selectedModel}
        status={status}
        error={error}
        liveRecognitionEnabled={liveRecognitionEnabled}
        liveSourceMode={liveRecognitionModeRef.current || sourceMode}
        realtimeTargetFps={realtimeTargetFps}
        realtimeProfile={realtimeProfile}
        realtimeMetrics={realtimeMetrics}
        onThresholdChange={setThreshold}
        onClose={closePictureInPictureWindow}
      />
    </section>
  );
}
