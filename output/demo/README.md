# Demo Assets

可直接用于演示的本地素材：

- 识别演示图片：`/home/bai/code/ai/plant-share-20260321-205124/output/demo/demo_leaf_train.png`
- 备用展示图片：`/home/bai/code/ai/plant-share-20260321-205124/output/demo/demo_leaf.png`
- 可导入数据集：`/home/bai/code/ai/plant-share-20260321-205124/output/demo/demo_leaf_dataset.zip`

已经准备好的系统内演示资源：

- 数据集名：`demo_leaf_live`
- 演示模型：`demo_leaf_live.onnx`

推荐演示顺序：

1. 登录管理员账号。
2. 在“平台管理”里展示 `demo_leaf_live` 数据集和 `demo_leaf_live.onnx` 模型已经存在。
3. 在“模型资产”里展示演示模型可见且可切换。
4. 在“病害识别”里选择模型 `demo_leaf_live.onnx`。
5. 把置信度阈值调到 `1%`。
6. 上传 `demo_leaf_train.png`，即可看到检测框结果。
7. 在“标注与训练”里切到数据集 `demo_leaf_live`，展示类别、样本和训练入口。
8. 如果要演示导入流程，再用 `demo_leaf_dataset.zip` 新建一个临时数据集导入。

已完成验证：

- `python3 tools/full_feature_check.py`
- `python3 tools/api_smoke_check.py`
- `npx playwright test tests/e2e/auth-persistence.spec.cjs tests/e2e/ui-core.spec.cjs --reporter=line --workers=1 --timeout=60000`
