export const APP_NAME = "PlantOps";
export const APP_TAGLINE = "植物病害识别平台";
export const AUTH_STORAGE_KEY = "plant_auth_token";
export const DEFAULT_WORKSPACE = "recognition";

export const WORKSPACES = [
  {
    id: "recognition",
    label: "病害识别",
    navGlyph: "R",
    group: "flow",
    groupLabel: "主流程",
    step: "01",
    hint: "上传、摄像头、录屏",
    summary: "上传图片、摄像头或共享屏幕后，直接获得检测框、主预测与分析建议。",
    focusTitle: "先拿到稳定识别结果",
    focusSummary: "先确认主预测和检测框稳定，再把结果送去标注训练。",
    highlights: ["图片 / 摄像头 / 录屏输入", "识别结果可直接送去标注", "模型切换和阈值控制同页完成"],
  },
  {
    id: "annotation",
    label: "标注与训练",
    navGlyph: "A",
    group: "flow",
    groupLabel: "主流程",
    step: "02",
    hint: "数据集、增强、训练",
    summary: "围绕数据集、框选、增强和训练形成闭环，所有写入操作都在网页内完成。",
    focusTitle: "把识别结果沉淀成可训练数据",
    focusSummary: "在同一画布里修正识别框、保存标注并发起训练。",
    highlights: ["识别框可直接导入辅助标注", "YOLO 数据集保存和下载", "训练进度在当前页持续更新"],
  },
  {
    id: "details",
    label: "模型资产",
    navGlyph: "M",
    group: "support",
    groupLabel: "其他功能",
    step: "03",
    hint: "上传、下载、切换",
    summary: "统一处理模型上传、下载、切换和启用。",
    focusTitle: "统一管理可用模型",
    focusSummary: "把当前可用模型、个人模型和在线模型收进一个页面。",
    highlights: ["上传个人模型并立即接入识别", "下载、切换和归档集中处理", "公开模型与个人模型统一管理"],
  },
  {
    id: "admin",
    label: "平台管理",
    navGlyph: "S",
    group: "support",
    groupLabel: "其他功能",
    step: "04",
    hint: "用户、模型、脚本",
    summary: "管理员统一维护用户、模型、数据集和增强脚本。",
    focusTitle: "管理员总控",
    focusSummary: "把平台资源管理与普通工作流隔离，减少主链路干扰。",
    highlights: ["统一查看用户与资源", "上传模型、数据集、增强脚本", "切换在线模型与增强算法"],
  },
];

export function getWorkspaceMeta(workspaceId) {
  return WORKSPACES.find((workspace) => workspace.id === workspaceId) || WORKSPACES[0];
}
