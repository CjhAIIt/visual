import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  addAnnotationClass,
  augmentAnnotationDataset,
  createAnnotationDataset,
  deleteAnnotationClass,
  deleteAnnotationDataset,
  downloadAnnotationSourceImage,
  downloadAnnotationDataset,
  fetchAnnotationClasses,
  fetchModels,
  fetchAnnotationSourceImageDetail,
  importAnnotationDatasetFolder,
  fetchTrainingTask,
  saveAnnotationFile,
  startTrainingTask,
  uploadAnnotationSourceImages,
} from "@/lib/plantApi";
import { saveBlobAsFile } from "@/lib/download";
import { validateImageFile } from "@/lib/imageFiles";

function revokeUrl(url) {
  if (url) {
    URL.revokeObjectURL(url);
  }
}

function normalizeBox(box) {
  return {
    label: box.label,
    x1: Math.min(box.x1, box.x2),
    y1: Math.min(box.y1, box.y2),
    x2: Math.max(box.x1, box.x2),
    y2: Math.max(box.y1, box.y2),
    source: box.source || "manual",
  };
}

function toFixedBox(box) {
  return {
    label: box.label,
    x1: Number(box.x1.toFixed(2)),
    y1: Number(box.y1.toFixed(2)),
    x2: Number(box.x2.toFixed(2)),
    y2: Number(box.y2.toFixed(2)),
    source: box.source || "manual",
  };
}

function getDatasetMeta(datasetItems, datasetName, fallback = {}) {
  return datasetItems.find((item) => item.name === datasetName) || {
    name: datasetName || "",
    is_public: Boolean(fallback.selected_dataset_is_public),
    is_official: Boolean(fallback.selected_dataset_is_official),
    can_write: Boolean(fallback.selected_dataset_can_write),
    owner_username: String(fallback.selected_dataset_owner_username || ""),
    owner_display_name: String(fallback.selected_dataset_owner_display_name || ""),
  };
}

function boxContainsPoint(box, x, y) {
  return x >= box.x1 && x <= box.x2 && y >= box.y1 && y <= box.y2;
}

function formatPercent(progress) {
  const numeric = Number(progress);
  if (!Number.isFinite(numeric)) {
    return "0%";
  }
  return `${Math.max(0, Math.min(100, Math.round(numeric * 100)))}%`;
}

function boxStyle(box, imageMeta) {
  if (!imageMeta.width || !imageMeta.height) {
    return null;
  }
  return {
    left: `${(box.x1 / imageMeta.width) * 100}%`,
    top: `${(box.y1 / imageMeta.height) * 100}%`,
    width: `${((box.x2 - box.x1) / imageMeta.width) * 100}%`,
    height: `${((box.y2 - box.y1) / imageMeta.height) * 100}%`,
  };
}

function readPoint(event, frameElement, imageMeta) {
  if (!frameElement || !imageMeta.width || !imageMeta.height) {
    return null;
  }
  const rect = frameElement.getBoundingClientRect();
  const xRatio = (event.clientX - rect.left) / rect.width;
  const yRatio = (event.clientY - rect.top) / rect.height;
  if (xRatio < 0 || xRatio > 1 || yRatio < 0 || yRatio > 1) {
    return null;
  }
  return {
    x: xRatio * imageMeta.width,
    y: yRatio * imageMeta.height,
  };
}

function getTemplateLabel(templates, key) {
  if (!key) {
    return "未匹配";
  }
  if (key === "custom") {
    return "自定义类别库";
  }
  return templates.find((item) => item.key === key)?.label || key;
}

function getDatasetOwnerLabel(datasetMeta) {
  if (!datasetMeta) {
    return "未分配";
  }
  return datasetMeta.owner_display_name || datasetMeta.owner_username || (datasetMeta.is_official ? "官方资源" : "当前用户");
}

function createInitialDatasetState() {
  return {
    loading: false,
    datasetItems: [],
    selectedDataset: "",
    classes: [],
    classTemplates: [],
    selectedTemplateKey: "",
    classAdvices: [],
    datasetMeta: null,
    sourceImages: [],
    counts: { source: 0, annotated: 0, train: 0, val: 0 },
    hint: "",
  };
}

export function AnnotationWorkspace({
  token,
  isAuthenticated,
  recognitionPayload = null,
}) {
  const imageInputRef = useRef(null);
  const sourceFolderInputRef = useRef(null);
  const datasetFolderImportInputRef = useRef(null);
  const frameRef = useRef(null);
  const activeTaskRef = useRef("");
  const previousDatasetRef = useRef("");
  const pendingBoxSelectionRef = useRef("");

  const [datasetState, setDatasetState] = useState(() => createInitialDatasetState());
  const [models, setModels] = useState([]);
  const [selectedClass, setSelectedClass] = useState("");
  const [imageFile, setImageFile] = useState(null);
  const [imageUrl, setImageUrl] = useState("");
  const [imageMeta, setImageMeta] = useState({ width: 0, height: 0 });
  const [boxes, setBoxes] = useState([]);
  const [draftBox, setDraftBox] = useState(null);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [selectedSourceImageName, setSelectedSourceImageName] = useState("");
  const [status, setStatus] = useState("登录后即可在这里管理数据集、框选标注并发起训练任务。");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploadingSourceImages, setUploadingSourceImages] = useState(false);
  const [loadingSourceImageName, setLoadingSourceImageName] = useState("");
  const [importingDatasetFolder, setImportingDatasetFolder] = useState(false);
  const [augmenting, setAugmenting] = useState(false);
  const [training, setTraining] = useState(false);
  const [datasetCreateName, setDatasetCreateName] = useState("");
  const [datasetPublic, setDatasetPublic] = useState(false);
  const [datasetCreateMode, setDatasetCreateMode] = useState("template");
  const [datasetTemplateKey, setDatasetTemplateKey] = useState("blank");
  const [datasetImportName, setDatasetImportName] = useState("");
  const [datasetImportPublic, setDatasetImportPublic] = useState(false);
  const [datasetImportFiles, setDatasetImportFiles] = useState([]);
  const [datasetImportRelativePaths, setDatasetImportRelativePaths] = useState([]);
  const [datasetImportFolderLabel, setDatasetImportFolderLabel] = useState("");
  const [customClass, setCustomClass] = useState("");
  const [augmentCopies, setAugmentCopies] = useState(2);
  const [focusMode, setFocusMode] = useState(false);
  const [annotationView, setAnnotationView] = useState(() => (recognitionPayload?.file ? "annotate" : "dataset"));
  const [trainForm, setTrainForm] = useState({
    baseModel: "yolov8n.pt",
    modelName: "",
    epochs: 50,
    imgsz: 640,
  });
  const [trainTask, setTrainTask] = useState(null);
  const canOperate = Boolean(isAuthenticated && token);

  useEffect(() => {
    return () => revokeUrl(imageUrl);
  }, [imageUrl]);

  useEffect(() => {
    const previousDataset = previousDatasetRef.current;
    const currentDataset = datasetState.selectedDataset;
    const datasetChanged = previousDataset && previousDataset !== currentDataset;

    if (datasetChanged) {
      setBoxes([]);
      setDraftBox(null);
      setSelectedIndex(-1);
      if (selectedSourceImageName) {
        revokeUrl(imageUrl);
        setImageFile(null);
        setImageUrl("");
        setImageMeta({ width: 0, height: 0 });
        setSelectedSourceImageName("");
      }
    }

    if (!currentDataset && imageUrl) {
      revokeUrl(imageUrl);
      setImageFile(null);
      setImageUrl("");
      setImageMeta({ width: 0, height: 0 });
      setFocusMode(false);
    }

    previousDatasetRef.current = currentDataset;
  }, [datasetState.selectedDataset, imageUrl, selectedSourceImageName]);

  useEffect(() => {
    if (!imageUrl) {
      setFocusMode(false);
    }
  }, [imageUrl]);

  useEffect(() => {
    if (pendingBoxSelectionRef.current === "last") {
      pendingBoxSelectionRef.current = "";
      setSelectedIndex(boxes.length ? boxes.length - 1 : -1);
      return;
    }
    if (selectedIndex >= boxes.length) {
      setSelectedIndex(boxes.length ? boxes.length - 1 : -1);
    }
  }, [boxes.length, selectedIndex]);

  useEffect(() => {
    if (!focusMode) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        setFocusMode(false);
      }
    };

    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [focusMode]);

  useEffect(() => {
    if (!isAuthenticated || !token) {
      revokeUrl(imageUrl);
      setDatasetState(createInitialDatasetState());
      setModels([]);
      setSelectedClass("");
      setImageFile(null);
      setImageUrl("");
      setImageMeta({ width: 0, height: 0 });
      setBoxes([]);
      setDraftBox(null);
      setSelectedIndex(-1);
      setSelectedSourceImageName("");
      setDatasetImportFiles([]);
      setDatasetImportRelativePaths([]);
      setDatasetImportFolderLabel("");
      setTrainTask(null);
      activeTaskRef.current = "";
      return;
    }

    let cancelled = false;
    async function bootstrap() {
      setDatasetState((current) => ({ ...current, loading: true }));
      try {
        const [classesPayload, modelsPayload] = await Promise.all([
          fetchAnnotationClasses(token),
          fetchModels(token),
        ]);
        if (cancelled) {
          return;
        }
        applyAnnotationPayload(classesPayload?.data || {});
        const availableModels = Array.isArray(modelsPayload?.data?.available_models) ? modelsPayload.data.available_models : [];
        setModels(availableModels);
        if (availableModels.length && !trainForm.baseModel) {
          setTrainForm((current) => ({ ...current, baseModel: availableModels[0] }));
        }
      } catch (nextError) {
        if (!cancelled) {
          setError(nextError.message || "标注数据初始化失败。");
        }
      } finally {
        if (!cancelled) {
          setDatasetState((current) => ({ ...current, loading: false }));
        }
      }
    }

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, token]);

  function applyAnnotationPayload(data) {
    const datasetItems = Array.isArray(data.available_dataset_items) && data.available_dataset_items.length
      ? data.available_dataset_items
      : (data.available_datasets || []).map((name) => ({ name }));
    const selectedDataset = data.selected_dataset || datasetItems[0]?.name || "";
    const classes = Array.isArray(data.classes) ? data.classes : [];
    const classTemplates = Array.isArray(data.class_templates) ? data.class_templates : [];
    const classAdvices = Array.isArray(data.class_advices) ? data.class_advices : [];
    const sourceImages = Array.isArray(data.source_images) ? data.source_images : [];
    const datasetMeta = selectedDataset ? getDatasetMeta(datasetItems, selectedDataset, data) : null;
    const selectedTemplateKey = data.selected_dataset_template_key || "";
    setDatasetState({
      loading: false,
      datasetItems,
      selectedDataset,
      classes,
      classTemplates,
      selectedTemplateKey,
      classAdvices,
      datasetMeta,
      sourceImages,
      counts: {
        source: Number(data.source_image_count) || 0,
        annotated: Number(data.annotated_source_count ?? data.source_pair_count) || 0,
        train: Number(data.train_pair_count) || 0,
        val: Number(data.val_pair_count) || 0,
      },
      hint: selectedDataset
        ? `数据集 ${selectedDataset} ｜ 原始图片 ${Number(data.source_image_count) || 0} ｜ 已标注 ${Number(data.annotated_source_count ?? data.source_pair_count) || 0} ｜ train ${Number(data.train_pair_count) || 0} ｜ val ${Number(data.val_pair_count) || 0}`
        : "当前没有可访问数据集。",
    });
    setDatasetTemplateKey((current) => {
      if (current && classTemplates.some((item) => item.key === current)) {
        return current;
      }
      if (selectedTemplateKey && classTemplates.some((item) => item.key === selectedTemplateKey)) {
        return selectedTemplateKey;
      }
      return classTemplates.find((item) => item.key === "corn")?.key
        || classTemplates.find((item) => item.key === "blank")?.key
        || classTemplates[0]?.key
        || "";
    });
    setSelectedClass((current) => (classes.includes(current) ? current : (classes[0] || "")));
  }

  function handleSelectedClassChange(nextClass) {
    setSelectedClass(nextClass);
    if (selectedIndex >= 0) {
      setBoxes((current) => current.map((item, index) => (
        index === selectedIndex ? { ...item, label: nextClass } : item
      )));
    }
  }

  async function reloadAnnotationData(datasetName = datasetState.selectedDataset) {
    if (!token) {
      return;
    }
    setDatasetState((current) => ({ ...current, loading: true }));
    try {
      setError("");
      const payload = await fetchAnnotationClasses(token, datasetName);
      applyAnnotationPayload(payload?.data || {});
    } catch (nextError) {
      setError(nextError.message || "标注数据加载失败。");
    } finally {
      setDatasetState((current) => ({ ...current, loading: false }));
    }
  }

  async function handleDatasetCreate() {
    if (!datasetCreateName.trim()) {
      setError("请先输入数据集名称。");
      return;
    }
    if (datasetCreateMode === "template" && !datasetTemplateKey) {
      setError("请先选择一个类别模板。");
      return;
    }
    try {
      setError("");
      const payload = await createAnnotationDataset(token, {
        dataset_name: datasetCreateName.trim(),
        source_dataset: datasetCreateMode === "clone" ? datasetState.selectedDataset || undefined : undefined,
        is_public: datasetPublic,
        class_template_key: datasetCreateMode === "template" ? datasetTemplateKey : undefined,
      });
      applyAnnotationPayload(payload?.data || {});
      setDatasetCreateName("");
      setDatasetPublic(false);
      setStatus(
        datasetCreateMode === "clone"
          ? `数据集 ${payload?.data?.selected_dataset || datasetCreateName.trim()} 已按当前类别库复制创建。`
          : `数据集 ${payload?.data?.selected_dataset || datasetCreateName.trim()} 已按模板创建。`,
      );
    } catch (nextError) {
      setError(nextError.message || "数据集创建失败。");
    }
  }

  async function handleDatasetDelete() {
    if (!datasetState.selectedDataset) {
      return;
    }
    if (!window.confirm(`确定删除数据集“${datasetState.selectedDataset}”吗？`)) {
      return;
    }
    const deletingDataset = datasetState.selectedDataset;
    try {
      setDatasetState((current) => ({ ...current, loading: true }));
      setError("");
      const payload = await deleteAnnotationDataset(token, deletingDataset);
      applyAnnotationPayload(payload?.data || {});
      setStatus(payload?.message || `数据集 ${deletingDataset} 已删除。`);
    } catch (nextError) {
      setError(nextError.message || "数据集删除失败。");
    } finally {
      setDatasetState((current) => ({ ...current, loading: false }));
    }
  }

  async function handleDatasetDownload() {
    if (!datasetState.selectedDataset) {
      return;
    }
    try {
      const blob = await downloadAnnotationDataset(token, datasetState.selectedDataset);
      saveBlobAsFile(blob, `${datasetState.selectedDataset}_dataset.zip`);
      setStatus(`数据集 ${datasetState.selectedDataset} 已开始下载。`);
    } catch (nextError) {
      setError(nextError.message || "数据集下载失败。");
    }
  }

  async function handleAddClass() {
    if (!customClass.trim() || !datasetState.selectedDataset) {
      setError("请先选择数据集并输入类别名。");
      return;
    }
    try {
      setError("");
      const payload = await addAnnotationClass(token, datasetState.selectedDataset, customClass.trim());
      applyAnnotationPayload(payload?.data || {});
      setSelectedClass((payload?.data?.classes || []).find((item) => item === customClass.trim()) || customClass.trim());
      setCustomClass("");
      setStatus(payload?.message || `类别 ${customClass.trim()} 已加入当前数据集。`);
    } catch (nextError) {
      setError(nextError.message || "类别添加失败。");
    }
  }

  async function handleDeleteClass() {
    if (!datasetState.selectedDataset || !selectedClass) {
      return;
    }
    if (!window.confirm(`确定删除类别“${selectedClass}”吗？`)) {
      return;
    }
    try {
      setError("");
      const deletingClass = selectedClass;
      const payload = await deleteAnnotationClass(token, datasetState.selectedDataset, deletingClass);
      applyAnnotationPayload(payload?.data || {});
      setBoxes((current) => current.filter((item) => item.label !== deletingClass));
      setSelectedIndex(-1);
      setStatus(`类别 ${deletingClass} 已删除。`);
    } catch (nextError) {
      setError(nextError.message || "类别删除失败。");
    }
  }

  function setImageFromFile(file, nextStatus, { nextBoxes = [], sourceImageName = "" } = {}) {
    revokeUrl(imageUrl);
    setImageFile(file);
    setImageUrl(URL.createObjectURL(file));
    setBoxes(nextBoxes);
    setDraftBox(null);
    setSelectedIndex(-1);
    setSelectedSourceImageName(sourceImageName);
    setAnnotationView("annotate");
    setStatus(nextStatus);
    setError("");
  }

  function handleImageChange(event) {
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
    setImageFromFile(file, `已载入图片 ${file.name}，现在可以开始框选标注。`);
    event.target.value = "";
  }

  async function handleSourceFolderUpload(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length || !datasetState.selectedDataset) {
      event.target.value = "";
      return;
    }

    for (const file of files) {
      const validationError = validateImageFile(file);
      if (validationError) {
        setError(`${file.name}：${validationError}`);
        event.target.value = "";
        return;
      }
    }

    try {
      setUploadingSourceImages(true);
      setError("");
      const payload = await uploadAnnotationSourceImages(token, {
        datasetName: datasetState.selectedDataset,
        files,
      });
      applyAnnotationPayload(payload?.data || {});
      setStatus(payload?.message || `已导入 ${files.length} 张图片。`);
      setAnnotationView("annotate");
    } catch (nextError) {
      setError(nextError.message || "批量导入原始图片失败。");
    } finally {
      setUploadingSourceImages(false);
      event.target.value = "";
    }
  }

  function openDatasetFolderImportPicker() {
    datasetFolderImportInputRef.current?.click();
  }

  function handleDatasetFolderImportSelection(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) {
      setDatasetImportFiles([]);
      setDatasetImportRelativePaths([]);
      setDatasetImportFolderLabel("");
      return;
    }

    const relativePaths = files.map((file) => String(file.webkitRelativePath || file.name || "").replace(/\\/g, "/"));
    const rootCandidate = relativePaths[0]?.split("/")[0] || "";
    setDatasetImportFiles(files);
    setDatasetImportRelativePaths(relativePaths);
    setDatasetImportFolderLabel(rootCandidate || files[0]?.name || "已选目录");
    if (!datasetImportName && rootCandidate) {
      setDatasetImportName(rootCandidate);
    }
    setError("");
    event.target.value = "";
  }

  async function handleDatasetFolderImport() {
    if (!datasetImportFiles.length) {
      setError("请先选择本地数据集文件夹。");
      return;
    }

    try {
      setImportingDatasetFolder(true);
      setError("");
      const payload = await importAnnotationDatasetFolder(token, {
        datasetName: datasetImportName.trim(),
        isPublic: datasetImportPublic,
        files: datasetImportFiles,
        relativePaths: datasetImportRelativePaths,
      });
      applyAnnotationPayload(payload?.data || {});
      setDatasetImportFiles([]);
      setDatasetImportRelativePaths([]);
      setDatasetImportFolderLabel("");
      setDatasetImportName("");
      setDatasetImportPublic(false);
      setStatus(payload?.message || "本地数据集已导入。");
      setAnnotationView("dataset");
    } catch (nextError) {
      setError(nextError.message || "本地数据集导入失败。");
    } finally {
      setImportingDatasetFolder(false);
    }
  }

  async function loadDatasetSourceImage(imageName) {
    if (!token || !datasetState.selectedDataset || !imageName) {
      return;
    }

    try {
      setLoadingSourceImageName(imageName);
      setError("");
      const [detailPayload, blob] = await Promise.all([
        fetchAnnotationSourceImageDetail(token, datasetState.selectedDataset, imageName),
        downloadAnnotationSourceImage(token, datasetState.selectedDataset, imageName),
      ]);
      const detail = detailPayload?.data || {};
      const file = new File([blob], detail.image_name || imageName, {
        type: blob.type || "image/jpeg",
      });
      const nextBoxes = Array.isArray(detail.annotations) ? detail.annotations : [];
      setImageFromFile(
        file,
        detail.has_annotation
          ? `已载入 ${detail.image_name || imageName}，恢复 ${nextBoxes.length} 个标注框。`
          : `已载入 ${detail.image_name || imageName}，可以开始标注。`,
        {
          nextBoxes,
          sourceImageName: detail.image_name || imageName,
        },
      );
    } catch (nextError) {
      setError(nextError.message || "载入数据集图片失败。");
    } finally {
      setLoadingSourceImageName("");
    }
  }

  function openSourceFolderPicker() {
    sourceFolderInputRef.current?.click();
  }

  function handleLoadNextPendingSourceImage() {
    if (!nextPendingSourceImage) {
      setError("当前没有待标注的原始图片。");
      return;
    }
    loadDatasetSourceImage(nextPendingSourceImage.name);
  }

  function handleUseRecognitionImage() {
    if (!recognitionPayload?.file) {
      setError("当前没有来自识别页的图片。");
      return;
    }
    setImageFromFile(recognitionPayload.file, `已导入识别页图片 ${recognitionPayload.file.name}。`);
  }

  function handleImportDetections() {
    if (!recognitionPayload?.result?.detections?.length || !datasetState.classes.length) {
      setError("当前没有可导入的检测框。");
      return;
    }
    const supported = recognitionPayload.result.detections
      .filter((item) => Array.isArray(item.bbox) && item.bbox.length === 4 && datasetState.classes.includes(item.label))
      .map((item) => normalizeBox({
        label: item.label,
        x1: item.bbox[0],
        y1: item.bbox[1],
        x2: item.bbox[2],
        y2: item.bbox[3],
        source: "assist",
      }));
    if (!supported.length) {
      setError("当前识别结果和数据集类别没有交集，无法直接导入。");
      return;
    }
    pendingBoxSelectionRef.current = "last";
    setBoxes((current) => current.concat(supported));
    setStatus(`已导入 ${supported.length} 个识别框，可继续人工修正。`);
  }

  function handlePointerDown(event) {
    if (!imageMeta.width || !imageMeta.height || !selectedClass) {
      return;
    }
    const point = readPoint(event, frameRef.current, imageMeta);
    if (!point) {
      return;
    }

    for (let index = boxes.length - 1; index >= 0; index -= 1) {
      if (boxContainsPoint(boxes[index], point.x, point.y)) {
        setSelectedIndex(index);
        setSelectedClass(boxes[index].label);
        return;
      }
    }

    setSelectedIndex(-1);
    setDraftBox({
      label: selectedClass,
      x1: point.x,
      y1: point.y,
      x2: point.x,
      y2: point.y,
      source: "manual",
    });
  }

  function handlePointerMove(event) {
    if (!draftBox) {
      return;
    }
    const point = readPoint(event, frameRef.current, imageMeta);
    if (!point) {
      return;
    }
    setDraftBox((current) => current ? { ...current, x2: point.x, y2: point.y } : current);
  }

  function finalizeDraft(event) {
    if (!draftBox) {
      return;
    }
    const point = readPoint(event, frameRef.current, imageMeta);
    const nextDraft = point ? { ...draftBox, x2: point.x, y2: point.y } : draftBox;
    const normalized = normalizeBox(nextDraft);
    setDraftBox(null);
    if (normalized.x2 - normalized.x1 < 4 || normalized.y2 - normalized.y1 < 4) {
      return;
    }
    pendingBoxSelectionRef.current = "last";
    setBoxes((current) => current.concat(normalized));
  }

  function handleDeleteSelectedBox() {
    if (selectedIndex < 0 || !boxes[selectedIndex]) {
      return;
    }
    setBoxes((current) => current.filter((_, index) => index !== selectedIndex));
    setSelectedIndex(-1);
  }

  function handleClearBoxes() {
    pendingBoxSelectionRef.current = "";
    setBoxes([]);
    setDraftBox(null);
    setSelectedIndex(-1);
  }

  async function handleSaveAnnotations() {
    if (!imageFile || !boxes.length || !datasetState.selectedDataset) {
      setError("请先准备图片、标注框和目标数据集。");
      return;
    }
    try {
      setSaving(true);
      setError("");
      const payload = await saveAnnotationFile(token, {
        file: selectedSourceImageName ? null : imageFile,
        datasetName: datasetState.selectedDataset,
        annotations: boxes.map(toFixedBox),
        sourceFilename: selectedSourceImageName || undefined,
      });
      setStatus(`保存成功：${payload?.data?.filename} 已写入数据集 ${payload?.data?.dataset_name}。`);
      await reloadAnnotationData(datasetState.selectedDataset);
    } catch (nextError) {
      setError(nextError.message || "标注保存失败。");
    } finally {
      setSaving(false);
    }
  }

  async function handleAugment() {
    if (!datasetState.selectedDataset) {
      return;
    }
    try {
      setAugmenting(true);
      setError("");
      const payload = await augmentAnnotationDataset(token, {
        dataset_name: datasetState.selectedDataset,
        copies: Number(augmentCopies),
        train_ratio: 0.8,
      });
      setStatus(`增强完成：${payload?.data?.dataset_name || datasetState.selectedDataset}，train ${payload?.data?.train_count ?? 0} / val ${payload?.data?.val_count ?? 0}。`);
      await reloadAnnotationData(datasetState.selectedDataset);
    } catch (nextError) {
      setError(nextError.message || "数据增强失败。");
    } finally {
      setAugmenting(false);
    }
  }

  async function handleTrain() {
    if (!datasetState.selectedDataset) {
      return;
    }
    if (!datasetState.classes.length) {
      setError("当前数据集还没有类别，不能直接启动训练。");
      return;
    }
    try {
      setTraining(true);
      setError("");
      const payload = await startTrainingTask(token, {
        dataset_name: datasetState.selectedDataset,
        base_model: trainForm.baseModel,
        model_name: trainForm.modelName || undefined,
        epochs: Number(trainForm.epochs),
        imgsz: Number(trainForm.imgsz),
      });
      const task = payload?.data || null;
      if (!task?.task_id) {
        throw new Error("训练任务创建成功，但没有返回 task_id。");
      }
      activeTaskRef.current = task.task_id;
      setTrainTask(task);
      setStatus(`训练任务已启动：${task.task_id}`);
    } catch (nextError) {
      setTraining(false);
      setError(nextError.message || "训练任务启动失败。");
    }
  }

  useEffect(() => {
    if (!trainTask?.task_id || !training) {
      return;
    }
    let cancelled = false;
    async function poll() {
      try {
        const payload = await fetchTrainingTask(token, trainTask.task_id);
        if (cancelled || activeTaskRef.current !== trainTask.task_id) {
          return;
        }
        const nextTask = payload?.data || null;
        setTrainTask(nextTask);
        if (nextTask?.status === "completed") {
          setTraining(false);
          setStatus(`训练完成：${nextTask?.result?.model_name || "新模型"} 已生成。`);
          return;
        }
        if (nextTask?.status === "failed") {
          setTraining(false);
          setError(nextTask?.error || nextTask?.message || "训练失败。");
          return;
        }
        window.setTimeout(poll, 2000);
      } catch (nextError) {
        if (!cancelled) {
          setError(nextError.message || "训练进度获取失败。");
          setTraining(false);
        }
      }
    }
    const timer = window.setTimeout(poll, 2000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [token, trainTask, training]);

  const draftStyle = useMemo(() => (draftBox ? boxStyle(normalizeBox(draftBox), imageMeta) : null), [draftBox, imageMeta]);
  const canWrite = Boolean(datasetState.datasetMeta?.can_write);
  const currentSourceImageMeta = useMemo(
    () => datasetState.sourceImages.find((item) => item.name === selectedSourceImageName) || null,
    [datasetState.sourceImages, selectedSourceImageName],
  );
  const nextPendingSourceImage = useMemo(() => {
    if (!datasetState.sourceImages.length) {
      return null;
    }
    const ordered = datasetState.sourceImages;
    const currentIndex = ordered.findIndex((item) => item.name === selectedSourceImageName);
    if (currentIndex >= 0) {
      for (let index = currentIndex + 1; index < ordered.length; index += 1) {
        if (!ordered[index].has_annotation) {
          return ordered[index];
        }
      }
    }
    return ordered.find((item) => !item.has_annotation) || null;
  }, [datasetState.sourceImages, selectedSourceImageName]);
  const selectedClassAdvice = useMemo(
    () => datasetState.classAdvices.find((item) => item.class_name === selectedClass) || null,
    [datasetState.classAdvices, selectedClass],
  );
  const selectedBox = selectedIndex >= 0 ? boxes[selectedIndex] || null : null;
  const selectedDatasetTemplateLabel = useMemo(
    () => getTemplateLabel(datasetState.classTemplates, datasetState.selectedTemplateKey),
    [datasetState.classTemplates, datasetState.selectedTemplateKey],
  );
  const createTemplate = useMemo(
    () => datasetState.classTemplates.find((item) => item.key === datasetTemplateKey) || null,
    [datasetState.classTemplates, datasetTemplateKey],
  );
  const visibleTemplateCards = useMemo(
    () => datasetState.classTemplates.filter((item) => item.key !== "universal" || item.class_count > 0),
    [datasetState.classTemplates],
  );

  function renderAnnotationStageSurface(stageClassName = "annotation-stage") {
    return (
      <div className={stageClassName}>
        {imageUrl ? (
          <div
            ref={frameRef}
            className="annotation-stage__frame"
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={finalizeDraft}
            onPointerLeave={finalizeDraft}
          >
            <img
              src={imageUrl}
              alt="标注图片"
              onLoad={(event) => {
                setImageMeta({
                  width: event.currentTarget.naturalWidth,
                  height: event.currentTarget.naturalHeight,
                });
              }}
            />
            <div className="annotation-stage__overlay" aria-hidden="true">
              {boxes.map((box, index) => {
                const style = boxStyle(box, imageMeta);
                if (!style) {
                  return null;
                }
                return (
                  <button
                    key={`${box.label}-${index}-${box.x1}`}
                    type="button"
                    className={`annotation-box${selectedIndex === index ? " is-active" : ""}${box.source === "assist" ? " is-assist" : ""}`}
                    style={style}
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedIndex(index);
                      setSelectedClass(box.label);
                    }}
                  >
                    <span>{box.label}</span>
                  </button>
                );
              })}
              {draftStyle ? <span className="annotation-box annotation-box--draft" style={draftStyle} /> : null}
            </div>
          </div>
        ) : (
          <div className="native-empty">
            <strong>还没有标注图片</strong>
            <p>可以单独上传图片，也可以直接接收识别页中的图片和检测框。</p>
          </div>
        )}
      </div>
    );
  }

  const annotationViewTabs = [
    {
      id: "dataset",
      label: "数据集准备",
      summary: datasetState.selectedDataset || "先选数据集",
    },
    {
      id: "annotate",
      label: "标注",
      summary: imageFile?.name || (boxes.length ? `${boxes.length} 个框` : "导入图片开始框选"),
    },
    {
      id: "train",
      label: "训练",
      summary: trainTask?.status || (training ? "训练中" : "增强并启动训练"),
    },
  ];
  const currentAnnotationTab = annotationViewTabs.find((item) => item.id === annotationView) || annotationViewTabs[0];

  function renderStatusFeedback() {
    return (
      <div className="native-feedback">
        <p>{status}</p>
        {error ? <strong>{error}</strong> : null}
      </div>
    );
  }

  function renderDatasetControls() {
    return (
      <>
        <div className="annotation-intro-card">
          <div>
            <span>当前数据集</span>
            <strong>{datasetState.selectedDataset || "尚未选择"}</strong>
          </div>
          <div>
            <span>类别模板</span>
            <strong>{selectedDatasetTemplateLabel}</strong>
          </div>
          <div>
            <span>写入权限</span>
            <strong>{canWrite ? "可写入" : "只读"}</strong>
          </div>
        </div>

        <div className="native-workspace__group annotation-sidebar__section annotation-sidebar__section--dataset">
          <div className="annotation-sidebar__section-head">
            <div>
              <p className="workspace__section-label">01 Dataset</p>
              <h4>当前数据集概况</h4>
            </div>
            <span className={`native-pill ${canWrite ? "native-pill--accent" : "native-pill--neutral"}`}>
              {canWrite ? "可写入" : "只读"}
            </span>
          </div>

          <label className="native-field">
            <span>切换数据集</span>
            <select
              value={datasetState.selectedDataset}
              onChange={(event) => reloadAnnotationData(event.target.value)}
              disabled={!canOperate || datasetState.loading}
            >
              {!datasetState.datasetItems.length ? <option value="">{datasetState.loading ? "正在加载..." : "暂无数据集"}</option> : null}
              {datasetState.datasetItems.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>

          <div className="annotation-dataset-overview">
            <article className="annotation-dataset-overview__card">
              <span>所属</span>
              <strong>{getDatasetOwnerLabel(datasetState.datasetMeta)}</strong>
            </article>
            <article className="annotation-dataset-overview__card">
              <span>开放性</span>
              <strong>{datasetState.datasetMeta?.is_public ? "公开数据集" : "私有数据集"}</strong>
            </article>
            <article className="annotation-dataset-overview__card">
              <span>类别范围</span>
              <strong>{selectedDatasetTemplateLabel}</strong>
            </article>
          </div>

          <p className="native-hint">{datasetState.hint || "创建数据集后即可开始保存标注。"}</p>

          <div className="annotation-sidebar__stats">
            <article className="annotation-sidebar__stat">
              <span>原始图片</span>
              <strong>{datasetState.counts.source}</strong>
            </article>
            <article className="annotation-sidebar__stat">
              <span>已标注</span>
              <strong>{datasetState.counts.annotated}</strong>
            </article>
            <article className="annotation-sidebar__stat">
              <span>Train</span>
              <strong>{datasetState.counts.train}</strong>
            </article>
            <article className="annotation-sidebar__stat">
              <span>Val</span>
              <strong>{datasetState.counts.val}</strong>
            </article>
          </div>

          <div className="native-inline-actions">
            <button
              type="button"
              className="primary"
              onClick={openSourceFolderPicker}
              disabled={!canOperate || !canWrite || !datasetState.selectedDataset || uploadingSourceImages}
            >
              {uploadingSourceImages ? "导入中..." : "上传图片文件夹"}
            </button>
            <button type="button" className="secondary" onClick={handleDatasetDownload} disabled={!canOperate || !datasetState.selectedDataset}>
              下载数据集
            </button>
            <button type="button" className="secondary" onClick={handleDatasetDelete} disabled={!canOperate || !datasetState.selectedDataset || !canWrite}>
              删除数据集
            </button>
          </div>
        </div>

        <div className="native-workspace__group annotation-sidebar__section annotation-sidebar__section--classes">
          <div className="annotation-sidebar__section-head">
            <div>
              <p className="workspace__section-label">02 Classes</p>
              <h4>类别库与建议</h4>
            </div>
            <span className="native-pill native-pill--neutral">{datasetState.classes.length} 类</span>
          </div>

          <label className="native-field">
            <span>当前类别</span>
            <select value={selectedClass} onChange={(event) => handleSelectedClassChange(event.target.value)} disabled={!canOperate || !datasetState.classes.length}>
              {!datasetState.classes.length ? <option value="">暂无类别</option> : null}
              {datasetState.classes.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>

          <div className="native-inline-actions">
            <input value={customClass} onChange={(event) => setCustomClass(event.target.value)} placeholder="新增类别，例如 Corn leaf curl" disabled={!canOperate || !canWrite} />
            <button type="button" className="secondary" onClick={handleAddClass} disabled={!canOperate || !canWrite}>
              添加
            </button>
            <button type="button" className="secondary" onClick={handleDeleteClass} disabled={!canOperate || !canWrite || !selectedClass || datasetState.classes.length <= 1}>
              删除
            </button>
          </div>

          <div className="annotation-class-cloud">
            {datasetState.classes.length ? (
              datasetState.classes.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`annotation-class-cloud__item${selectedClass === item ? " is-active" : ""}`}
                  onClick={() => handleSelectedClassChange(item)}
                >
                  {item}
                </button>
              ))
            ) : (
              <span className="annotation-class-cloud__empty">当前数据集还没有类别，先选模板或手动新增类别。</span>
            )}
          </div>

          {selectedClassAdvice ? (
            <div className="annotation-advice-card">
              <div className="annotation-advice-card__head">
                <strong>{selectedClassAdvice.class_name}</strong>
                <span>知识库建议</span>
              </div>
              <p>{selectedClassAdvice.summary}</p>
              {selectedClassAdvice.detail ? <p className="annotation-advice-card__meta">{selectedClassAdvice.detail}</p> : null}
              <ul className="native-list native-list--stacked">
                {selectedClassAdvice.advice.map((item) => (
                  <li key={item} className="native-list__item native-list__item--stacked">
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="annotation-advice-card annotation-advice-card--placeholder">
              <div className="annotation-advice-card__head">
                <strong>{selectedClass || "尚未选择类别"}</strong>
                <span>建议区</span>
              </div>
              <p>新增类别后会自动调用实验室大模型生成建议并写入知识库缓存，后续识别和推荐会直接复用。</p>
            </div>
          )}
        </div>

        <div className="native-workspace__group annotation-sidebar__section annotation-sidebar__section--create">
          <div className="annotation-sidebar__section-head">
            <div>
              <p className="workspace__section-label">03 Create</p>
              <h4>新建数据集</h4>
            </div>
            <span className="native-pill native-pill--neutral">
              {datasetCreateMode === "template" ? "模板建库" : "复制类别"}
            </span>
          </div>

          <div className="annotation-mode-switch">
            <button
              type="button"
              className={`annotation-mode-switch__item${datasetCreateMode === "template" ? " is-active" : ""}`}
              onClick={() => setDatasetCreateMode("template")}
            >
              按作物模板创建
            </button>
            <button
              type="button"
              className={`annotation-mode-switch__item${datasetCreateMode === "clone" ? " is-active" : ""}`}
              onClick={() => setDatasetCreateMode("clone")}
            >
              复制当前类别库
            </button>
          </div>

          <label className="native-field">
            <span>数据集名称</span>
            <input
              value={datasetCreateName}
              onChange={(event) => setDatasetCreateName(event.target.value)}
              placeholder="例如 corn_leaf_stage2"
              disabled={!canOperate}
            />
          </label>

          {datasetCreateMode === "template" ? (
            <div className="annotation-template-grid">
              {visibleTemplateCards.map((template) => (
                <button
                  key={template.key}
                  type="button"
                  className={`annotation-template-card${datasetTemplateKey === template.key ? " is-active" : ""}`}
                  onClick={() => setDatasetTemplateKey(template.key)}
                  disabled={!canOperate}
                >
                  <div className="annotation-template-card__head">
                    <strong>{template.label}</strong>
                    <span>{template.class_count} 类</span>
                  </div>
                  <p>{template.description}</p>
                  <div className="annotation-template-card__preview">
                    {template.classes.slice(0, 3).map((item) => (
                      <span key={item}>{item}</span>
                    ))}
                    {!template.classes.length ? <span>空白起步</span> : null}
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="annotation-clone-card">
              <strong>{datasetState.selectedDataset || "暂无可复制数据集"}</strong>
              <p>复制模式会沿用当前数据集的类别集合，适合做版本迭代或精修集。</p>
            </div>
          )}

          {datasetCreateMode === "template" && createTemplate ? (
            <div className="annotation-template-summary">
              <strong>{createTemplate.label}</strong>
              <p>{createTemplate.description}</p>
            </div>
          ) : null}

          <label className="native-checkbox">
            <input type="checkbox" checked={datasetPublic} onChange={(event) => setDatasetPublic(event.target.checked)} disabled={!canOperate} />
            <span>创建为公开数据集</span>
          </label>

          <div className="native-inline-actions">
            <button
              type="button"
              className="primary"
              onClick={handleDatasetCreate}
              disabled={!canOperate || (datasetCreateMode === "clone" && !datasetState.selectedDataset)}
            >
              创建并切换
            </button>
          </div>
        </div>

        <div className="native-workspace__group annotation-sidebar__section annotation-sidebar__section--create">
          <div className="annotation-sidebar__section-head">
            <div>
              <p className="workspace__section-label">04 Import</p>
              <h4>导入本地现成数据集</h4>
            </div>
            <span className="native-pill native-pill--neutral">
              目录直传
            </span>
          </div>

          <p className="native-hint">
            这里导入的是已经整理好的本地数据集目录，例如包含 `classes.txt`、`images/`、`labels/` 的 YOLO 结构。
          </p>

          <div className="annotation-clone-card">
            <strong>{datasetImportFolderLabel || "尚未选择目录"}</strong>
            <p>{datasetImportFiles.length ? `已选 ${datasetImportFiles.length} 个文件，可直接导入。` : "点击下面按钮后选择本地数据集文件夹。支持直接选整个目录，不需要先手动压缩。"} </p>
          </div>

          <label className="native-field">
            <span>导入后数据集名称</span>
            <input
              value={datasetImportName}
              onChange={(event) => setDatasetImportName(event.target.value)}
              placeholder="留空则尝试使用目录名"
              disabled={!canOperate}
            />
          </label>

          <label className="native-checkbox">
            <input
              type="checkbox"
              checked={datasetImportPublic}
              onChange={(event) => setDatasetImportPublic(event.target.checked)}
              disabled={!canOperate}
            />
            <span>导入为公开数据集</span>
          </label>

          <div className="native-inline-actions">
            <button
              type="button"
              className="secondary"
              onClick={openDatasetFolderImportPicker}
              disabled={!canOperate || importingDatasetFolder}
            >
              选择本地数据集目录
            </button>
            <button
              type="button"
              className="primary"
              onClick={handleDatasetFolderImport}
              disabled={!canOperate || !datasetImportFiles.length || importingDatasetFolder}
            >
              {importingDatasetFolder ? "导入中..." : "导入现成数据集"}
            </button>
          </div>
        </div>

        {renderStatusFeedback()}
      </>
    );
  }

  function renderDatasetBoard() {
    return (
      <>
        <div className="native-workspace__section-head">
          <p className="workspace__section-label">Setup</p>
          <h3>先把数据集边界理顺</h3>
          <p>当前页只处理数据集、类别和建议。确认完类别范围，再进入标注或训练，流程会更清楚。</p>
        </div>

        <div className="annotation-ops-banner annotation-ops-banner--setup">
          <article className="annotation-ops-banner__card">
            <span>当前数据集</span>
            <strong>{datasetState.selectedDataset || "尚未选择"}</strong>
            <p>{datasetState.hint || "先切换或创建一个数据集。"}</p>
          </article>
          <article className="annotation-ops-banner__card">
            <span>有效类别</span>
            <strong>{datasetState.classes.length} 个</strong>
            <p>{selectedClass ? `当前选中 ${selectedClass}` : "先确认类别集合，再进入标注。"}</p>
          </article>
          <article className="annotation-ops-banner__card">
            <span>下一步</span>
            <strong>{datasetState.classes.length ? "进入标注" : "先准备类别"}</strong>
            <p>{datasetState.classes.length ? "类别已经就绪，建议先导入图片文件夹，再逐张标注。" : "没有类别时，不建议直接开始标注。"}</p>
          </article>
        </div>

        <div className="annotation-workflow-grid annotation-workflow-grid--setup">
          <section className="asset-collection">
            <div className="asset-collection__head">
              <div>
                <p className="workspace__section-label">Classes</p>
                <h3>当前类别边界</h3>
              </div>
              <span className="native-pill native-pill--neutral">{datasetState.classes.length} 类</span>
            </div>
            <div className="annotation-class-cloud">
              {datasetState.classes.length ? (
                datasetState.classes.map((item) => (
                  <button
                    key={item}
                    type="button"
                    className={`annotation-class-cloud__item${selectedClass === item ? " is-active" : ""}`}
                    onClick={() => handleSelectedClassChange(item)}
                  >
                    {item}
                  </button>
                ))
              ) : (
                <span className="annotation-class-cloud__empty">当前还没有可用类别，先从模板建库或手动补充类别。</span>
              )}
            </div>
          </section>

          <section className="asset-collection">
            <div className="asset-collection__head">
              <div>
                <p className="workspace__section-label">Advice</p>
                <h3>当前类别建议</h3>
              </div>
              <span className="native-pill native-pill--neutral">{selectedClass || "未选择"}</span>
            </div>
            {selectedClassAdvice ? (
              <div className="annotation-advice-card">
                <div className="annotation-advice-card__head">
                  <strong>{selectedClassAdvice.class_name}</strong>
                  <span>知识库建议</span>
                </div>
                <p>{selectedClassAdvice.summary}</p>
                {selectedClassAdvice.detail ? <p className="annotation-advice-card__meta">{selectedClassAdvice.detail}</p> : null}
                <ul className="native-list native-list--stacked">
                  {selectedClassAdvice.advice.map((item) => (
                    <li key={item} className="native-list__item native-list__item--stacked">
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="native-empty native-empty--compact">
                <p>选择一个类别后，这里会显示知识库建议，方便你决定标注边界。</p>
              </div>
            )}
          </section>
        </div>

        <div className="annotation-toolbar annotation-toolbar--setup">
          <div className="annotation-toolbar__group">
            <button
              type="button"
              className="primary"
              onClick={openSourceFolderPicker}
              disabled={!canOperate || !canWrite || !datasetState.selectedDataset || uploadingSourceImages}
            >
              {uploadingSourceImages ? "导入中..." : "上传图片文件夹"}
            </button>
            <button type="button" className="secondary" onClick={() => imageInputRef.current?.click()} disabled={!canOperate}>
              直接导入图片
            </button>
            <button type="button" className="primary" onClick={() => setAnnotationView("annotate")} disabled={!datasetState.selectedDataset || !datasetState.classes.length}>
              进入标注
            </button>
            <button type="button" className="secondary" onClick={() => setAnnotationView("train")} disabled={!datasetState.selectedDataset || !datasetState.classes.length}>
              进入训练
            </button>
          </div>
        </div>
      </>
    );
  }

  function renderAnnotateControls() {
    return (
      <>
        <div className="annotation-intro-card annotation-intro-card--compact">
          <div>
            <span>当前数据集</span>
            <strong>{datasetState.selectedDataset || "尚未选择"}</strong>
          </div>
          <div>
            <span>当前类别</span>
            <strong>{selectedClass || "未选择"}</strong>
          </div>
          <div>
            <span>当前图片</span>
            <strong>{selectedSourceImageName || imageFile?.name || "未载入"}</strong>
          </div>
        </div>

        <div className="annotation-compact-grid">
          <label className="native-field">
            <span>切换数据集</span>
            <select value={datasetState.selectedDataset} onChange={(event) => reloadAnnotationData(event.target.value)} disabled={!canOperate || datasetState.loading}>
              {!datasetState.datasetItems.length ? <option value="">{datasetState.loading ? "正在加载..." : "暂无数据集"}</option> : null}
              {datasetState.datasetItems.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>

          <label className="native-field">
            <span>当前类别</span>
            <select value={selectedClass} onChange={(event) => handleSelectedClassChange(event.target.value)} disabled={!canOperate || !datasetState.classes.length}>
              {!datasetState.classes.length ? <option value="">暂无类别</option> : null}
              {datasetState.classes.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>

          <div className="native-inline-actions">
            <input value={customClass} onChange={(event) => setCustomClass(event.target.value)} placeholder="快速新增类别" disabled={!canOperate || !canWrite} />
            <button type="button" className="secondary" onClick={handleAddClass} disabled={!canOperate || !canWrite || !customClass.trim()}>
              添加类别
            </button>
            <button type="button" className="secondary" onClick={handleDeleteClass} disabled={!canOperate || !canWrite || !selectedClass || datasetState.classes.length <= 1}>
              删除类别
            </button>
          </div>
        </div>

        <div className="annotation-toolbar annotation-toolbar--compact">
          <div className="annotation-toolbar__group">
            <button
              type="button"
              className="primary"
              onClick={openSourceFolderPicker}
              disabled={!canOperate || !canWrite || !datasetState.selectedDataset || uploadingSourceImages}
            >
              {uploadingSourceImages ? "导入中..." : "上传图片文件夹"}
            </button>
            <button type="button" className="primary" onClick={() => imageInputRef.current?.click()} disabled={!canOperate}>
              选择标注图片
            </button>
            <button type="button" className="secondary" onClick={handleUseRecognitionImage} disabled={!canOperate || !recognitionPayload?.file}>
              使用识别图片
            </button>
            <button
              type="button"
              className="secondary"
              onClick={handleLoadNextPendingSourceImage}
              disabled={!canOperate || !nextPendingSourceImage || Boolean(loadingSourceImageName)}
            >
              {loadingSourceImageName ? "载入中..." : "下一张未标注"}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={handleImportDetections}
              disabled={!canOperate || !recognitionPayload?.result?.detections?.length || !imageFile}
            >
              导入识别框
            </button>
            <button type="button" className="secondary" onClick={() => setFocusMode(true)} disabled={!imageUrl}>
              专注标注
            </button>
          </div>
          <div className="annotation-toolbar__group">
            <button type="button" className="secondary" onClick={handleClearBoxes} disabled={!canOperate || !boxes.length}>
              清空标注
            </button>
            <button type="button" className="secondary" onClick={handleDeleteSelectedBox} disabled={!canOperate || selectedIndex < 0}>
              删除选中框
            </button>
            <button
              type="button"
              className="primary"
              onClick={handleSaveAnnotations}
              disabled={!canOperate || !canWrite || !imageFile || !boxes.length || saving}
            >
              {saving ? "保存中..." : "保存标注"}
            </button>
            <button type="button" className="secondary" onClick={() => setAnnotationView("train")} disabled={!datasetState.selectedDataset || !datasetState.classes.length}>
              进入训练
            </button>
          </div>
        </div>

        {selectedClassAdvice ? (
          <div className="annotation-advice-card">
            <div className="annotation-advice-card__head">
              <strong>{selectedClassAdvice.class_name}</strong>
              <span>当前类别建议</span>
            </div>
            <p>{selectedClassAdvice.summary}</p>
            {selectedClassAdvice.detail ? <p className="annotation-advice-card__meta">{selectedClassAdvice.detail}</p> : null}
          </div>
        ) : null}

        {renderStatusFeedback()}
      </>
    );
  }

  function renderAnnotateBoard() {
    return (
      <>
        <div className="native-workspace__section-head">
          <p className="workspace__section-label">Canvas</p>
          <h3>标注画面</h3>
          <p>图片导入、识别框复用、保存和框选都围绕同一块画布，避免右侧再拉出另一套操作区。</p>
        </div>

        <div className="annotation-ops-banner annotation-ops-banner--annotate">
          <article className="annotation-ops-banner__card">
            <span>类别范围</span>
            <strong>{selectedDatasetTemplateLabel}</strong>
            <p>{datasetState.classes.length ? `当前共 ${datasetState.classes.length} 个有效类别。` : "当前还没有可标注类别。"}</p>
          </article>
          <article className="annotation-ops-banner__card">
            <span>当前图片</span>
            <strong>{selectedSourceImageName || imageFile?.name || "未载入"}</strong>
            <p>
              {selectedSourceImageName
                ? `当前来自数据集原图队列${currentSourceImageMeta?.has_annotation ? "，已存在历史标注。" : "，尚未完成标注。"}`
                : imageFile
                  ? `已准备 ${boxes.length} 个标注框。`
                  : "可从本地上传，也可直接复用识别页图片。"}
            </p>
          </article>
          <article className="annotation-ops-banner__card">
            <span>当前状态</span>
            <strong>{selectedBox ? `已选中 ${selectedBox.label}` : "等待框选"}</strong>
            <p>{selectedBox ? "可以删除、修改类别或继续精修边界。" : "拖拽画布即可开始标注。"}</p>
          </article>
        </div>

        <div className="annotation-board__main">
          <div className="annotation-stage-wrap">
            {renderAnnotationStageSurface()}

            <div className="annotation-stage__caption">
              <span>
                {datasetState.classes.length
                  ? "拖拽画布即可框选。点击已有框可以快速切换到对应类别。"
                  : "当前数据集还没有类别，请先回到数据集准备补齐类别。"}
              </span>
              <strong>{selectedBox ? `当前选中：${selectedBox.label}` : "当前未选中任何标注框"}</strong>
            </div>
          </div>

          <aside className="annotation-context">
            <div className="annotation-context-card">
              <p className="workspace__section-label">Selected</p>
              <h4>当前选中项</h4>
              {selectedBox ? (
                <ul className="annotation-context-list">
                  <li>
                    <span>类别</span>
                    <strong>{selectedBox.label}</strong>
                  </li>
                  <li>
                    <span>来源</span>
                    <strong>{selectedBox.source === "assist" ? "识别辅助" : "手动标注"}</strong>
                  </li>
                  <li>
                    <span>坐标</span>
                    <strong>
                      {Math.round(selectedBox.x1)}, {Math.round(selectedBox.y1)} · {Math.round(selectedBox.x2)}, {Math.round(selectedBox.y2)}
                    </strong>
                  </li>
                </ul>
              ) : (
                <p>点击画布中的任意标注框后，这里会显示类别、来源和坐标。</p>
              )}
            </div>

            <div className="annotation-context-card">
              <p className="workspace__section-label">Dataset</p>
              <h4>当前类别边界</h4>
              <p>{selectedDatasetTemplateLabel}</p>
              <div className="annotation-context-pills">
                <span className="native-pill native-pill--neutral">{datasetState.classes.length} 个类别</span>
                <span className="native-pill native-pill--neutral">{datasetState.counts.source} 张原始图片</span>
                <span className="native-pill native-pill--neutral">{datasetState.counts.annotated} 张已标注</span>
              </div>
            </div>
          </aside>
        </div>

        <section className="asset-collection">
          <div className="asset-collection__head">
            <div>
              <p className="workspace__section-label">Queue</p>
              <h3>原图标注队列</h3>
            </div>
            <span className="native-pill native-pill--neutral">{datasetState.sourceImages.length} 张</span>
          </div>
          {!datasetState.sourceImages.length ? (
            <div className="native-empty native-empty--compact">
              <p>先上传图片文件夹，把原始图片放进当前数据集，再逐张标注。</p>
            </div>
          ) : (
            <div className="asset-rows">
              {datasetState.sourceImages.map((item) => (
                <article key={item.name} className={`asset-row asset-row--compact${selectedSourceImageName === item.name ? " is-active" : ""}`}>
                  <div className="asset-row__main">
                    <div className="asset-row__title">
                      <strong>{item.name}</strong>
                      <div className="asset-row__badges">
                        <span className={`native-pill ${item.has_annotation ? "native-pill--accent" : "native-pill--neutral"}`}>
                          {item.has_annotation ? `已标注 ${item.annotation_count}` : "待标注"}
                        </span>
                      </div>
                    </div>
                    <p>{item.updated_at || "刚刚导入"}</p>
                  </div>
                  <div className="asset-row__actions">
                    <button
                      type="button"
                      className="secondary native-utility-button"
                      onClick={() => loadDatasetSourceImage(item.name)}
                      disabled={loadingSourceImageName === item.name}
                    >
                      {loadingSourceImageName === item.name ? "载入中..." : (item.has_annotation ? "继续标注" : "开始标注")}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="asset-collection">
          <div className="asset-collection__head">
            <div>
              <p className="workspace__section-label">Boxes</p>
              <h3>标注列表</h3>
            </div>
            <span className="native-pill native-pill--neutral">{boxes.length} 个框</span>
          </div>
          {!boxes.length ? (
            <div className="native-empty native-empty--compact">
              <p>开始框选或导入识别框后，这里会显示所有标注项。</p>
            </div>
          ) : (
            <ul className="native-list native-list--stacked">
              {boxes.map((box, index) => (
                <li key={`${box.label}-${index}`} className={`native-list__item native-list__item--stacked${selectedIndex === index ? " is-active" : ""}`}>
                  <button
                    type="button"
                    className="native-list__button"
                    onClick={() => {
                      setSelectedIndex(index);
                      setSelectedClass(box.label);
                    }}
                  >
                    <strong>{box.label}</strong>
                    <span>{box.source === "assist" ? "识别辅助" : "手动标注"}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </>
    );
  }

  function renderTrainingControls() {
    return (
      <>
        <div className="annotation-intro-card annotation-intro-card--compact">
          <div>
            <span>当前数据集</span>
            <strong>{datasetState.selectedDataset || "尚未选择"}</strong>
          </div>
          <div>
            <span>类别数量</span>
            <strong>{datasetState.classes.length} 类</strong>
          </div>
          <div>
            <span>训练状态</span>
            <strong>{trainTask?.status || (training ? "训练中" : "待启动")}</strong>
          </div>
        </div>

        <label className="native-field">
          <span>切换数据集</span>
          <select value={datasetState.selectedDataset} onChange={(event) => reloadAnnotationData(event.target.value)} disabled={!canOperate || datasetState.loading}>
            {!datasetState.datasetItems.length ? <option value="">{datasetState.loading ? "正在加载..." : "暂无数据集"}</option> : null}
            {datasetState.datasetItems.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </label>

        <div className="annotation-training-grid annotation-training-grid--panel">
          <label className="native-field">
            <span>增强份数</span>
            <input type="number" min="1" value={augmentCopies} onChange={(event) => setAugmentCopies(event.target.value)} disabled={!canOperate || !canWrite} />
          </label>
          <label className="native-field">
            <span>基础模型</span>
            <input
              list="annotation-base-models"
              value={trainForm.baseModel}
              onChange={(event) => setTrainForm((current) => ({ ...current, baseModel: event.target.value }))}
              placeholder="例如 yolov8n.pt"
              disabled={!canOperate}
            />
            <datalist id="annotation-base-models">
              {models.map((item) => (
                <option key={item} value={item} />
              ))}
            </datalist>
          </label>
          <label className="native-field">
            <span>输出模型名</span>
            <input
              value={trainForm.modelName}
              onChange={(event) => setTrainForm((current) => ({ ...current, modelName: event.target.value }))}
              placeholder="可选"
              disabled={!canOperate}
            />
          </label>
          <label className="native-field">
            <span>Epochs</span>
            <input type="number" min="1" value={trainForm.epochs} onChange={(event) => setTrainForm((current) => ({ ...current, epochs: event.target.value }))} disabled={!canOperate} />
          </label>
          <label className="native-field">
            <span>Imgsz</span>
            <input type="number" min="32" value={trainForm.imgsz} onChange={(event) => setTrainForm((current) => ({ ...current, imgsz: event.target.value }))} disabled={!canOperate} />
          </label>
        </div>

        <div className="native-inline-actions">
          <button
            type="button"
            className="secondary"
            onClick={handleAugment}
            disabled={!canOperate || !canWrite || !datasetState.selectedDataset || augmenting}
          >
            {augmenting ? "增强中..." : "执行增强并划分 train/val"}
          </button>
          <button type="button" className="secondary" onClick={() => setAnnotationView("annotate")} disabled={!datasetState.selectedDataset}>
            回到标注
          </button>
          <button type="button" className="primary" onClick={handleTrain} disabled={!canOperate || !datasetState.selectedDataset || !datasetState.classes.length || training}>
            {training ? "训练中..." : "启动训练"}
          </button>
        </div>

        {renderStatusFeedback()}
      </>
    );
  }

  function renderTrainingBoard() {
    return (
      <>
        <div className="native-workspace__section-head">
          <p className="workspace__section-label">Train</p>
          <h3>增强与训练</h3>
          <p>这一屏只关心增强、训练配置和进度结果，不再混入标注画布和类别编辑。</p>
        </div>

        <div className="annotation-ops-banner annotation-ops-banner--train">
          <article className="annotation-ops-banner__card">
            <span>原始图片</span>
            <strong>{datasetState.counts.source}</strong>
            <p>当前数据集原图总量，适合用来跟踪待标注池规模。</p>
          </article>
          <article className="annotation-ops-banner__card">
            <span>已标注</span>
            <strong>{datasetState.counts.annotated}</strong>
            <p>真正可以参与增强和训练切分的原图数量。</p>
          </article>
          <article className="annotation-ops-banner__card">
            <span>训练集</span>
            <strong>{datasetState.counts.train}</strong>
            <p>执行增强后，训练集数量会在这里同步更新。</p>
          </article>
          <article className="annotation-ops-banner__card">
            <span>验证集</span>
            <strong>{datasetState.counts.val}</strong>
            <p>当前验证集规模，便于快速判断数据切分是否生效。</p>
          </article>
        </div>

        <div className="annotation-workflow-grid annotation-workflow-grid--train">
          <section className="asset-collection">
            <div className="asset-collection__head">
              <div>
                <p className="workspace__section-label">Progress</p>
                <h3>训练进度</h3>
              </div>
              <span className={`native-pill ${training ? "native-pill--warm" : "native-pill--neutral"}`}>
                {trainTask?.status || "待启动"}
              </span>
            </div>

            <div className="recognition-advice">
              {trainTask ? (
                <div className="train-progress">
                  <div className="train-progress__bar">
                    <span style={{ width: formatPercent(trainTask.progress) }} />
                  </div>
                  <div className="train-progress__meta">
                    <strong>{formatPercent(trainTask.progress)}</strong>
                    <span>{trainTask.message || trainTask.stage || trainTask.status}</span>
                  </div>
                  <ul className="native-list native-list--stacked">
                    <li className="native-list__item native-list__item--stacked">
                      <span>状态：{trainTask.status}</span>
                    </li>
                    <li className="native-list__item native-list__item--stacked">
                      <span>轮次：{trainTask.current_epoch || 0} / {trainTask.total_epochs || "--"}</span>
                    </li>
                    {trainTask.result?.model_name ? (
                      <li className="native-list__item native-list__item--stacked">
                        <span>输出模型：{trainTask.result.model_name}</span>
                      </li>
                    ) : null}
                  </ul>
                </div>
              ) : (
                <div className="native-empty native-empty--compact">
                  <p>启动训练任务后，这里会显示进度、阶段和结果模型。</p>
                </div>
              )}
            </div>
          </section>

          <section className="asset-collection">
            <div className="asset-collection__head">
              <div>
                <p className="workspace__section-label">Dataset</p>
                <h3>训练前检查</h3>
              </div>
              <span className="native-pill native-pill--neutral">{datasetState.selectedDataset || "未选择"}</span>
            </div>

            <div className="annotation-context-card">
              <p className="workspace__section-label">Ready Check</p>
              <h4>当前数据准备度</h4>
              <div className="annotation-context-pills">
                <span className="native-pill native-pill--neutral">{datasetState.classes.length} 个类别</span>
                <span className="native-pill native-pill--neutral">{boxes.length} 个当前框</span>
                <span className={`native-pill ${canWrite ? "native-pill--accent" : "native-pill--neutral"}`}>{canWrite ? "可写入" : "只读"}</span>
              </div>
              <p>
                {datasetState.classes.length
                  ? "类别集合已经准备好，可以执行增强并启动训练。"
                  : "当前数据集还没有类别，请先回到数据集准备。"}
              </p>
            </div>
          </section>
        </div>
      </>
    );
  }

  const focusOverlay = focusMode && imageUrl ? createPortal(
    <div className="annotation-focus" role="dialog" aria-modal="true" aria-label="专注标注模式">
      <div className="annotation-focus__shell">
        <header className="annotation-focus__toolbar">
          <div className="annotation-focus__toolbar-group">
            <div className="annotation-focus__meta">
              <span>数据集</span>
              <strong>{datasetState.selectedDataset || "--"}</strong>
            </div>
            <label className="native-field annotation-focus__field">
              <span>当前类别</span>
              <select value={selectedClass} onChange={(event) => handleSelectedClassChange(event.target.value)} disabled={!canOperate || !datasetState.classes.length}>
                {!datasetState.classes.length ? <option value="">暂无类别</option> : null}
                {datasetState.classes.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <input
              className="annotation-focus__quick-input"
              value={customClass}
              onChange={(event) => setCustomClass(event.target.value)}
              placeholder="新增类别"
              disabled={!canOperate || !canWrite}
            />
            <button type="button" className="secondary" onClick={handleAddClass} disabled={!canOperate || !canWrite || !customClass.trim()}>
              添加类别
            </button>
          </div>
          <div className="annotation-focus__toolbar-group annotation-focus__toolbar-group--actions">
            <button type="button" className="secondary" onClick={() => imageInputRef.current?.click()} disabled={!canOperate}>
              更换图片
            </button>
            <button
              type="button"
              className="secondary"
              onClick={handleImportDetections}
              disabled={!canOperate || !recognitionPayload?.result?.detections?.length || !imageFile}
            >
              导入识别框
            </button>
            <button type="button" className="secondary" onClick={handleDeleteSelectedBox} disabled={!canOperate || selectedIndex < 0}>
              删除选中框
            </button>
            <button type="button" className="primary" onClick={handleSaveAnnotations} disabled={!canOperate || !canWrite || !imageFile || !boxes.length || saving}>
              {saving ? "保存中..." : "保存标注"}
            </button>
            <button type="button" className="secondary" onClick={() => setFocusMode(false)}>
              退出全屏
            </button>
          </div>
        </header>

        <div className="annotation-focus__stage-wrap">
          {renderAnnotationStageSurface("annotation-stage annotation-stage--focus")}
        </div>

        <footer className="annotation-focus__dock">
          <div className="annotation-focus__summary">
            <span>当前状态</span>
            <strong>{selectedBox ? `已选中 ${selectedBox.label}` : "拖拽画布开始标注"}</strong>
            <p>
              {selectedBox
                ? `坐标 ${Math.round(selectedBox.x1)}, ${Math.round(selectedBox.y1)} · ${Math.round(selectedBox.x2)}, ${Math.round(selectedBox.y2)}`
                : "按 Esc 或右上角按钮退出全屏，普通页保留数据集管理和训练功能。"}
            </p>
          </div>
          <div className="annotation-focus__summary">
            <span>标注进度</span>
            <strong>{boxes.length} 个框</strong>
            <p>{selectedClassAdvice?.summary || "当前类别建议已收起到普通页左侧，专注模式只保留标注必需信息。"}</p>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  ) : null;

  return (
    <>
      <section className="native-workspace native-workspace--annotation">
        <input ref={imageInputRef} className="native-file-input" type="file" accept="image/*" onChange={handleImageChange} disabled={!canOperate} />
        <input
          ref={sourceFolderInputRef}
          className="native-file-input"
          type="file"
          accept="image/*"
          multiple
          webkitdirectory=""
          onChange={handleSourceFolderUpload}
          disabled={!canOperate || !canWrite}
        />
        <input
          ref={datasetFolderImportInputRef}
          className="native-file-input"
          type="file"
          multiple
          webkitdirectory=""
          onChange={handleDatasetFolderImportSelection}
          disabled={!canOperate}
        />

        <div className="native-workspace__panel native-workspace__panel--controls annotation-sidebar">
          <div className="native-workspace__section-head">
            <p className="workspace__section-label">Annotation</p>
            <h3>{currentAnnotationTab.label}</h3>
          </div>

          <div className="annotation-workspace-switch" role="tablist" aria-label="标注工作流阶段">
            {annotationViewTabs.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={annotationView === item.id}
                className={`annotation-workspace-switch__item${annotationView === item.id ? " is-active" : ""}`}
                onClick={() => setAnnotationView(item.id)}
              >
                <span>{item.label}</span>
                <strong>{item.summary}</strong>
              </button>
            ))}
          </div>

          {annotationView === "dataset" ? renderDatasetControls() : null}
          {annotationView === "annotate" ? renderAnnotateControls() : null}
          {annotationView === "train" ? renderTrainingControls() : null}
        </div>

        <div className="native-workspace__panel native-workspace__panel--canvas annotation-board">
          {annotationView === "dataset" ? renderDatasetBoard() : null}
          {annotationView === "annotate" ? renderAnnotateBoard() : null}
          {annotationView === "train" ? renderTrainingBoard() : null}
        </div>
      </section>
      {focusOverlay}
    </>
  );
}
