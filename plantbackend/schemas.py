from typing import List, Optional

from pydantic import BaseModel, Field


class PredictionItem(BaseModel):
    label: str
    confidence: float
    bbox: Optional[List[float]] = None


class AiAdviceData(BaseModel):
    disease_label: str
    summary: str
    advice: List[str]
    source: str
    detail: Optional[str] = None


class ClassAdviceData(BaseModel):
    class_name: str
    summary: str
    advice: List[str]
    source: str
    detail: Optional[str] = None
    generated_at: Optional[str] = None


class HealthData(BaseModel):
    status: str = Field(..., examples=["ok"])
    model_loaded: bool = Field(..., examples=[True])
    model_error: Optional[str] = Field(default=None, examples=[None])
    current_model: Optional[str] = Field(default=None, examples=["best.onnx"])
    available_models: List[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    success: bool
    message: str
    data: HealthData


class ModelsData(BaseModel):
    current_model: Optional[str]
    available_models: List[str]
    available_model_items: List["ModelAccessItem"] = Field(default_factory=list)


class ModelsResponse(BaseModel):
    success: bool
    message: str
    data: ModelsData


class ManagedModelItem(BaseModel):
    name: str
    size_bytes: int
    uploaded_at: Optional[str] = None
    has_labels: bool = False
    has_metadata: bool = False
    is_active: bool = False
    is_public: bool = False
    is_official: bool = False
    can_manage: bool = False
    owner_username: Optional[str] = None
    owner_display_name: Optional[str] = None


class ModelAccessItem(BaseModel):
    name: str
    is_active: bool = False
    is_public: bool = False
    is_official: bool = False
    can_manage: bool = False
    owner_username: Optional[str] = None
    owner_display_name: Optional[str] = None


class ManagedDatasetItem(BaseModel):
    name: str
    uploaded_at: Optional[str] = None
    is_public: bool = False
    is_official: bool = False
    can_manage: bool = False
    owner_username: Optional[str] = None
    owner_display_name: Optional[str] = None


class ManagedAugmentationItem(BaseModel):
    name: str
    size_bytes: int
    uploaded_at: Optional[str] = None
    is_active: bool = False
    is_builtin: bool = False
    display_name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    dataset_types: List[str] = Field(default_factory=list)
    author: Optional[str] = None


class AdminConsoleData(BaseModel):
    current_user: "UserProfile"
    current_model: Optional[str]
    available_models: List[str]
    managed_models: List[ManagedModelItem]
    managed_datasets: List[ManagedDatasetItem] = Field(default_factory=list)
    builtin_augmentation_script: Optional[str] = None
    active_augmentation_script: Optional[str] = None
    builtin_augmentation_item: Optional[ManagedAugmentationItem] = None
    managed_augmentation_scripts: List[ManagedAugmentationItem]


class AdminConsoleResponse(BaseModel):
    success: bool
    message: str
    data: AdminConsoleData


class UserProfile(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    dataset_count: int = 0
    model_count: int = 0
    is_disabled: bool = False
    is_flagged: bool = False


AdminConsoleData.model_rebuild()


class AuthSessionData(BaseModel):
    token: Optional[str] = None
    user: Optional[UserProfile] = None


class AuthSessionResponse(BaseModel):
    success: bool
    message: str
    data: AuthSessionData


class AuthLoginRequest(BaseModel):
    username: str
    password: str


class AuthRegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None


class UsersData(BaseModel):
    current_user: UserProfile
    users: List[UserProfile]


class UsersResponse(BaseModel):
    success: bool
    message: str
    data: UsersData


class ToggleValueRequest(BaseModel):
    value: bool


class ModelDeleteRequest(BaseModel):
    model_name: str


class ModelTrainRequest(BaseModel):
    dataset_name: str
    base_model: Optional[str] = None
    model_name: Optional[str] = None
    epochs: Optional[int] = None
    imgsz: Optional[int] = None


class ModelTrainData(BaseModel):
    dataset_name: str
    model_name: str
    base_model: str
    epochs: int
    imgsz: int
    train_count: int
    val_count: int
    classes: List[str]
    onnx_path: str
    labels_path: str
    run_dir: str
    precision: Optional[float] = None
    recall: Optional[float] = None
    map50: Optional[float] = None
    map50_95: Optional[float] = None
    training_summary: Optional[str] = None
    training_advice: List[str] = Field(default_factory=list)
    current_model: Optional[str]
    available_models: List[str]


class ModelTrainResponse(BaseModel):
    success: bool
    message: str
    data: ModelTrainData


class ModelTrainTaskData(BaseModel):
    task_id: str
    dataset_name: str
    status: str
    progress: float
    stage: str
    message: str
    current_epoch: Optional[int] = None
    total_epochs: Optional[int] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    eta_seconds: Optional[int] = None
    estimated_finish_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[ModelTrainData] = None


class ModelTrainTaskResponse(BaseModel):
    success: bool
    message: str
    data: ModelTrainTaskData


class PredictData(BaseModel):
    filename: str
    model_name: Optional[str] = None
    predicted_class: str
    predicted_index: int
    confidence: float
    top_predictions: List[PredictionItem]
    detections: List[PredictionItem]
    ai_advice: Optional[AiAdviceData] = None
    ai_advice_included: bool = True
    prediction_ms: Optional[int] = None
    advice_ms: Optional[int] = None


class PredictResponse(BaseModel):
    success: bool
    message: str
    data: PredictData


class AiRecommendationRequest(BaseModel):
    disease_label: str
    dataset_name: Optional[str] = None
    confidence: Optional[float] = None
    top_predictions: List[PredictionItem] = Field(default_factory=list)


class AiRecommendationResponse(BaseModel):
    success: bool
    message: str
    data: AiAdviceData


class AnnotationBoxItem(BaseModel):
    label: str
    x1: float
    y1: float
    x2: float
    y2: float
    source: str = "manual"


class AnnotationSourceImageItem(BaseModel):
    name: str
    has_annotation: bool = False
    annotation_count: int = 0
    size_bytes: int = 0
    updated_at: Optional[str] = None


class AnnotationClassesData(BaseModel):
    selected_dataset: str
    available_datasets: List[str]
    available_dataset_items: List["AnnotationDatasetItem"] = Field(default_factory=list)
    classes: List[str]
    class_templates: List["AnnotationClassTemplateItem"] = Field(default_factory=list)
    class_advices: List[ClassAdviceData] = Field(default_factory=list)
    dataset_dir: str
    images_dir: str
    labels_dir: str
    source_pair_count: int
    source_image_count: int = 0
    annotated_source_count: int = 0
    source_images: List[AnnotationSourceImageItem] = Field(default_factory=list)
    train_pair_count: int
    val_pair_count: int
    selected_dataset_template_key: Optional[str] = None
    selected_dataset_is_public: bool = False
    selected_dataset_is_official: bool = False
    selected_dataset_owner_username: Optional[str] = None
    selected_dataset_owner_display_name: Optional[str] = None
    selected_dataset_can_write: bool = False


class AnnotationDatasetItem(BaseModel):
    name: str
    is_public: bool = False
    is_official: bool = False
    can_write: bool = False
    owner_username: Optional[str] = None
    owner_display_name: Optional[str] = None


class AnnotationClassTemplateItem(BaseModel):
    key: str
    label: str
    description: str
    class_count: int
    classes: List[str] = Field(default_factory=list)


class AnnotationClassesResponse(BaseModel):
    success: bool
    message: str
    data: AnnotationClassesData


class AnnotationSourceImageDetailData(BaseModel):
    dataset_name: str
    image_name: str
    has_annotation: bool = False
    annotation_count: int = 0
    image_path: str
    label_path: str
    annotations: List[AnnotationBoxItem] = Field(default_factory=list)


class AnnotationSourceImageDetailResponse(BaseModel):
    success: bool
    message: str
    data: AnnotationSourceImageDetailData


class AnnotationDatasetCreateRequest(BaseModel):
    dataset_name: str
    source_dataset: Optional[str] = None
    is_public: bool = False
    class_template_key: Optional[str] = None


class AnnotationDatasetDeleteRequest(BaseModel):
    dataset_name: str


class AnnotationClassCreateRequest(BaseModel):
    dataset_name: str
    class_name: str


class AnnotationClassDeleteRequest(BaseModel):
    dataset_name: str
    class_name: str


class AnnotationAugmentRequest(BaseModel):
    dataset_name: str
    copies: Optional[int] = None
    train_ratio: Optional[float] = None
    seed: Optional[int] = None


class AnnotationAugmentData(BaseModel):
    dataset_name: str
    source_count: int
    augmented_count: int
    total_count: int
    train_count: int
    val_count: int
    raw_images_dir: str
    train_images_dir: str
    val_images_dir: str


class AnnotationAugmentResponse(BaseModel):
    success: bool
    message: str
    data: AnnotationAugmentData


class AnnotationSaveData(BaseModel):
    dataset_name: str
    filename: str
    image_path: str
    label_path: str
    annotation_count: int
    saved_classes: List[str]


class AnnotationSaveResponse(BaseModel):
    success: bool
    message: str
    data: AnnotationSaveData


ModelsData.model_rebuild()
AnnotationClassesData.model_rebuild()
