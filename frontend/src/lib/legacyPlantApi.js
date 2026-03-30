import { requestApi, requestBlob } from "@/lib/api";

function appendOptionalFile(formData, key, file) {
  if (file) {
    formData.append(key, file);
  }
}

export async function predictImage(token, file, modelName = "", signal, {
  includeAiAdvice = true,
  confidenceThreshold = null,
} = {}) {
  const formData = new FormData();
  formData.append("file", file);
  const params = new URLSearchParams();
  if (modelName) {
    params.set("model_name", modelName);
  }
  params.set("include_ai_advice", String(Boolean(includeAiAdvice)));
  if (typeof confidenceThreshold === "number" && Number.isFinite(confidenceThreshold)) {
    params.set("confidence_threshold", String(confidenceThreshold));
  }
  return requestApi(`/predict${params.toString() ? `?${params.toString()}` : ""}`, {
    method: "POST",
    token,
    body: formData,
    signal,
  });
}

export async function fetchAnnotationClasses(token, dataset = "", signal) {
  const params = new URLSearchParams();
  if (dataset) {
    params.set("dataset", dataset);
  }
  return requestApi(`/annotation/classes${params.toString() ? `?${params.toString()}` : ""}`, {
    token,
    signal,
  });
}

export async function createAnnotationDataset(token, payload) {
  return requestApi("/annotation/datasets", {
    method: "POST",
    token,
    body: payload,
  });
}

export async function importAnnotationDatasetFolder(token, {
  datasetName = "",
  isPublic = false,
  files = [],
  relativePaths = [],
}) {
  const formData = new FormData();
  if (datasetName) {
    formData.append("dataset_name", datasetName);
  }
  formData.append("is_public", String(Boolean(isPublic)));
  Array.from(files).forEach((file, index) => {
    formData.append("files", file);
    formData.append("relative_paths", relativePaths[index] || file.webkitRelativePath || file.name || `file_${index}`);
  });
  return requestApi("/annotation/datasets/import-folder", {
    method: "POST",
    token,
    body: formData,
  });
}

export async function uploadAnnotationSourceImages(token, { datasetName = "", files = [] }) {
  const formData = new FormData();
  if (datasetName) {
    formData.append("dataset_name", datasetName);
  }
  Array.from(files).forEach((file) => {
    formData.append("files", file);
  });
  return requestApi("/annotation/source-images/upload", {
    method: "POST",
    token,
    body: formData,
  });
}

export async function fetchAnnotationSourceImageDetail(token, datasetName, imageName) {
  return requestApi(`/annotation/source-images/${encodeURIComponent(datasetName)}/${encodeURIComponent(imageName)}/detail`, {
    token,
  });
}

export async function downloadAnnotationSourceImage(token, datasetName, imageName) {
  return requestBlob(`/annotation/source-images/${encodeURIComponent(datasetName)}/${encodeURIComponent(imageName)}`, {
    token,
  });
}

export async function deleteAnnotationDataset(token, datasetName) {
  return requestApi("/annotation/datasets/delete", {
    method: "POST",
    token,
    body: { dataset_name: datasetName },
  });
}

export async function downloadAnnotationDataset(token, datasetName) {
  return requestBlob(`/annotation/datasets/${encodeURIComponent(datasetName)}/download`, {
    token,
  });
}

export async function addAnnotationClass(token, datasetName, className) {
  return requestApi("/annotation/classes", {
    method: "POST",
    token,
    body: {
      dataset_name: datasetName,
      class_name: className,
    },
  });
}

export async function deleteAnnotationClass(token, datasetName, className) {
  return requestApi("/annotation/classes/delete", {
    method: "POST",
    token,
    body: {
      dataset_name: datasetName,
      class_name: className,
    },
  });
}

export async function augmentAnnotationDataset(token, payload) {
  return requestApi("/annotation/augment", {
    method: "POST",
    token,
    body: payload,
  });
}

export async function saveAnnotationFile(token, { file, datasetName, annotations, sourceFilename = "" }) {
  const formData = new FormData();
  if (file) {
    formData.append("file", file);
  }
  formData.append("dataset_name", datasetName);
  formData.append("annotations", JSON.stringify(annotations));
  if (sourceFilename) {
    formData.append("source_filename", sourceFilename);
  }
  return requestApi("/annotation/save", {
    method: "POST",
    token,
    body: formData,
  });
}

export async function startTrainingTask(token, payload) {
  return requestApi("/models/train/tasks", {
    method: "POST",
    token,
    body: payload,
  });
}

export async function fetchTrainingTask(token, taskId, signal) {
  return requestApi(`/models/train/tasks/${encodeURIComponent(taskId)}`, {
    token,
    signal,
  });
}

export async function uploadUserModel(token, {
  modelFile,
  labelsFile,
  metadataFile,
  activate = false,
  isPublic = false,
}) {
  const formData = new FormData();
  formData.append("model_file", modelFile);
  appendOptionalFile(formData, "labels_file", labelsFile);
  appendOptionalFile(formData, "metadata_file", metadataFile);
  formData.append("activate", String(Boolean(activate)));
  formData.append("is_public", String(Boolean(isPublic)));
  return requestApi("/models/upload", {
    method: "POST",
    token,
    body: formData,
  });
}

export async function deleteModelAsset(token, modelName) {
  return requestApi("/models/delete", {
    method: "POST",
    token,
    body: { model_name: modelName },
  });
}

export async function selectActiveModel(token, modelName) {
  const params = new URLSearchParams();
  params.set("model_name", modelName);
  return requestApi(`/models/select?${params.toString()}`, {
    method: "POST",
    token,
  });
}