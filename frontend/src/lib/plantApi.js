import { requestApi, requestBlob } from "@/lib/api";

export async function fetchModels(token, signal) {
  return requestApi("/models", { token, signal });
}

export async function downloadModelArchive(token, modelName) {
  return requestBlob(`/models/${encodeURIComponent(modelName)}/download`, {
    token,
  });
}

export {
  addAnnotationClass,
  augmentAnnotationDataset,
  createAnnotationDataset,
  deleteAnnotationClass,
  deleteAnnotationDataset,
  deleteModelAsset,
  downloadAnnotationDataset,
  downloadAnnotationSourceImage,
  fetchAnnotationClasses,
  fetchAnnotationSourceImageDetail,
  fetchTrainingTask,
  importAnnotationDatasetFolder,
  predictImage,
  saveAnnotationFile,
  selectActiveModel,
  startTrainingTask,
  uploadAnnotationSourceImages,
  uploadUserModel,
} from "@/lib/legacyPlantApi";