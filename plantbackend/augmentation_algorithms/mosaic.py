import cv2
import numpy as np
import os
import glob
from PIL import Image
import random


class MosaicAugmentation:
    """
    Mosaic数据增强类
    功能：将4张图像拼接成一张大图，用于目标检测任务的数据增强
    """

    def __init__(self, target_size=640, fill_value=114):
        """
        初始化Mosaic增强参数

        参数说明:
            target_size: 输出图像的目标尺寸（宽高相等），默认640x640像素
            fill_value: 空白区域的填充颜色值，默认114（RGB=114,114,114，灰色）
        """
        # 初始化Mosaic增强参数
        self.target_size = target_size  # 输出图像的目标尺寸（宽高相等）
        self.fill_value = fill_value  # 空白区域的填充颜色值（RGB=114,114,114，灰色）

    def _handle_insufficient_images(self, images, labels):
        """
        处理图像数量不足4张的情况

        参数说明:
            images: 输入图像列表
            labels: 对应的标签列表

        返回:
            blank_image: 空白图像（当没有输入图像时）
            或调用mosaic_augmentation处理补足4张后的图像
        """
        # 检查图像列表是否为空
        if len(images) == 0:
            # 如果没有图像，返回空白图像（填充指定颜色）
            blank_image = np.full((self.target_size, self.target_size, 3),
                                  self.fill_value, dtype=np.uint8)
            return blank_image, []  # 返回空白图像和空标签列表

        # 复制图像直到有4张（如果不足4张）
        while len(images) < 4:
            images.append(images[-1].copy())  # 复制最后一张图像
            labels.append(labels[-1].copy())  # 复制对应的标签

        # 递归调用mosaic_augmentation，现在有4张图像了
        return self.mosaic_augmentation(images, labels)

    def mosaic_augmentation(self, images, labels):
        """
        执行Mosaic数据增强的主函数
        将4张图像拼接成一张大图，并调整对应的标签坐标

        参数说明:
            images: 包含4张图像的列表，每张图像为numpy数组
            labels: 对应的标签列表，每个标签格式为[[class, x, y, w, h], ...]

        返回:
            mosaic_images: 拼接后的Mosaic图像
            mosaic_labels: 转换后的标签列表
        """
        # 检查图像数量，如果不足4张则先处理
        if len(images) < 4:
            return self._handle_insufficient_images(images, labels)

        # 创建目标画布，用指定颜色填充
        # 使用np.full创建指定大小的数组，并用fill_value填充
        mosaic_images = np.full((self.target_size, self.target_size, 3),
                                self.fill_value, dtype=np.uint8)
        mosaic_labels = []  # 存储转换后的标签

        # 随机生成分割点，将画布分成4个区域
        # 分割点在画布的1/4到3/4范围内随机选择，确保每个区域都有足够空间
        split_x = random.randint(self.target_size // 4, 3 * self.target_size // 4)
        split_y = random.randint(self.target_size // 4, 3 * self.target_size // 4)

        # 定义四个区域的坐标范围（左上角x, 左上角y, 右下角x, 右下角y）
        split_point = [
            (0, 0, split_x, split_y),  # 左上区域
            (split_x, 0, self.target_size, split_y),  # 右上区域
            (0, split_y, split_x, self.target_size),  # 左下区域
            (split_x, split_y, self.target_size, self.target_size)  # 右下区域
        ]

        # 处理每张图像和对应的标签
        for i, (a_x1, a_y1, a_x2, a_y2) in enumerate(split_point):
            # 如果图像数量不足4张，提前结束循环（理论上不会发生，因为前面已处理）
            if i >= len(images):
                break

            img = images[i]  # 获取第i张图像
            img_label = labels[i]  # 获取第i张图像的标签

            # 计算当前区域的宽度和高度
            region_width = a_x2 - a_x1  # 区域宽度
            region_height = a_y2 - a_y1  # 区域高度

            # 获取原始图像的尺寸（高度、宽度）
            h, w = img.shape[:2]

            # 计算缩放比例，保持宽高比，使图像能适应区域
            # 选择宽度和高度的最小缩放比例，确保图像完全包含在区域内
            scale = min(region_height / h, region_width / w)

            # 计算缩放后的新尺寸（保持宽高比）
            new_height = int(h * scale)
            new_width = int(w * scale)

            # 调整图像尺寸
            if scale != 1:
                # 使用OpenCV的resize函数调整图像大小
                # INTER_LINEAR插值方法提供较好的质量和速度平衡
                resize_img = cv2.resize(img, (new_width, new_height),
                                        interpolation=cv2.INTER_LINEAR)
            else:
                resize_img = img  # 如果不需要缩放，直接使用原图

            # 计算图像在区域中的起始位置（居中放置）
            # 计算居中偏移量，使图像在区域中心显示
            start_x = a_x1 + (region_width - new_width) // 2
            start_y = a_y1 + (region_height - new_height) // 2

            # 将调整后的图像放置到画布的对应区域
            # 使用numpy数组切片操作将图像复制到指定位置
            mosaic_images[start_y:start_y + new_height,
            start_x:start_x + new_width] = resize_img

            # 转换标签坐标：将原始图像上的标签坐标转换到Mosaic图像上的坐标
            for label in img_label:
                if len(label) < 5:  # 确保标签格式正确 [class, x, y, w, h]
                    continue

                # 解析标签：类别ID和边界框的归一化坐标
                class_id, x_center, y_center, width, height = label

                # 将归一化坐标转换为像素坐标（相对于原始图像尺寸）
                x_center_pixel = x_center * w  # x中心点像素坐标
                y_center_pixel = y_center * h  # y中心点像素坐标
                width_pixel = width * w  # 宽度像素值
                height_pixel = height * h  # 高度像素值

                # 应用缩放：将原始图像上的坐标按比例缩放到适应区域的大小
                x_center_scaled = x_center_pixel * scale
                y_center_scaled = y_center_pixel * scale
                width_scaled = width_pixel * scale
                height_scaled = height_pixel * scale

                # 应用偏移：将缩放后的坐标转换到Mosaic图像中的绝对位置
                # 加上图像在Mosaic中的起始位置偏移量
                x_center_final = x_center_scaled + start_x
                y_center_final = y_center_scaled + start_y

                # 计算边界框的四个角点（用于检查边界框是否在图像内）
                x_min = x_center_final - width_scaled / 2  # 左上角x
                y_min = y_center_final - height_scaled / 2  # 左上角y
                x_max = x_center_final + width_scaled / 2  # 右下角x
                y_max = y_center_final + height_scaled / 2  # 右下角y

                # 检查边界框是否完全在mosaic图像内
                if (x_min >= 0 and y_min >= 0 and
                        x_max <= self.target_size and y_max <= self.target_size and
                        width_scaled > 0 and height_scaled > 0):
                    # 如果边界框完全在图像内，直接使用完整边界框

                    # 计算新的中心点坐标（归一化到mosaic图像尺寸）
                    x_center_norm = x_center_final / self.target_size
                    y_center_norm = y_center_final / self.target_size
                    width_norm = width_scaled / self.target_size
                    height_norm = height_scaled / self.target_size

                    # 添加到mosaic标签列表
                    mosaic_labels.append([
                        class_id,  # 类别ID保持不变
                        x_center_norm,  # 归一化x中心坐标
                        y_center_norm,  # 归一化y中心坐标
                        width_norm,  # 归一化宽度
                        height_norm  # 归一化高度
                    ])
                else:
                    # 如果边界框不完全在图像内，检查是否有部分可见
                    # 计算可见部分（边界框与图像边界的交集）
                    visible_x_min = max(0, x_min)  # 可见区域左边界
                    visible_y_min = max(0, y_min)  # 可见区域上边界
                    visible_x_max = min(self.target_size, x_max)  # 可见区域右边界
                    visible_y_max = min(self.target_size, y_max)  # 可见区域下边界

                    # 计算可见部分的宽度和高度
                    visible_width = visible_x_max - visible_x_min
                    visible_height = visible_y_max - visible_y_min

                    # 如果可见部分足够大（例如面积大于原始面积的20%），则保留
                    original_area = width_scaled * height_scaled  # 原始边界框面积
                    visible_area = visible_width * visible_height  # 可见部分面积

                    # 面积阈值检查：只保留可见面积大于原始面积20%的边界框
                    if visible_area > original_area * 0.2 and visible_width > 0 and visible_height > 0:
                        # 计算可见部分的中心点
                        visible_center_x = (visible_x_min + visible_x_max) / 2
                        visible_center_y = (visible_y_min + visible_y_max) / 2

                        # 归一化坐标（相对于Mosaic图像尺寸）
                        x_center_norm = visible_center_x / self.target_size
                        y_center_norm = visible_center_y / self.target_size
                        width_norm = visible_width / self.target_size
                        height_norm = visible_height / self.target_size

                        # 添加到mosaic标签列表（只保留可见部分）
                        mosaic_labels.append([
                            class_id,  # 类别ID保持不变
                            x_center_norm,  # 归一化x中心坐标（可见部分）
                            y_center_norm,  # 归一化y中心坐标（可见部分）
                            width_norm,  # 归一化宽度（可见部分）
                            height_norm  # 归一化高度（可见部分）
                        ])
        # 返回拼接后的图像和转换后的标签
        return mosaic_images, mosaic_labels


