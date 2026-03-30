import { requestApi } from "@/lib/api";

function appendOptionalFile(formData, key, file) {
  if (file) {
    formData.append(key, file);
  }
}

export async function deleteUserAccount(token, userId) {
  return requestApi(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
    token,
  });
}

export async function uploadAdminModel(token, {
  modelFile,
  labelsFile,
  metadataFile,
  activate = false,
  isPublic = true,
}) {
  const formData = new FormData();
  formData.append("model_file", modelFile);
  appendOptionalFile(formData, "labels_file", labelsFile);
  appendOptionalFile(formData, "metadata_file", metadataFile);
  formData.append("activate", String(Boolean(activate)));
  formData.append("is_public", String(Boolean(isPublic)));
  return requestApi("/admin/models/upload", {
    method: "POST",
    token,
    body: formData,
  });
}

export async function uploadAdminDataset(token, {
  datasetFile,
  datasetName = "",
  isPublic = true,
}) {
  const formData = new FormData();
  formData.append("dataset_file", datasetFile);
  if (datasetName) {
    formData.append("dataset_name", datasetName);
  }
  formData.append("is_public", String(Boolean(isPublic)));
  return requestApi("/admin/datasets/upload", {
    method: "POST",
    token,
    body: formData,
  });
}

export async function uploadAdminAugmentation(token, {
  scriptFile,
  activate = true,
  displayName = "",
  version = "",
  datasetTypes = "",
  description = "",
  author = "",
}) {
  const formData = new FormData();
  formData.append("script_file", scriptFile);
  formData.append("activate", String(Boolean(activate)));
  if (displayName) {
    formData.append("display_name", displayName);
  }
  if (version) {
    formData.append("version", version);
  }
  if (datasetTypes) {
    formData.append("dataset_types", datasetTypes);
  }
  if (description) {
    formData.append("description", description);
  }
  if (author) {
    formData.append("author", author);
  }
  return requestApi("/admin/augmentations/upload", {
    method: "POST",
    token,
    body: formData,
  });
}

export async function selectAdminAugmentation(token, scriptName = "") {
  const params = new URLSearchParams();
  if (scriptName) {
    params.set("script_name", scriptName);
  }
  return requestApi(`/admin/augmentations/select${params.toString() ? `?${params.toString()}` : ""}`, {
    method: "POST",
    token,
  });
}