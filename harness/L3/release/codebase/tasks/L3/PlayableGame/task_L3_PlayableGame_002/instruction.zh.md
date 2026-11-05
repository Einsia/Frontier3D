请做一个能实际游玩的原创三维方块沙盒。基础内容包括草方块、泥土、石头、沙子、水、木头、树叶和火把；同一可探索世界中要有可辨识的平原、山地、沙漠、海洋与河流，地形可按种子重复生成。玩家能移动、观察、跳跃、破坏可破坏方块、收集掉落资源、选择物品并在合法位置放置方块。放置消耗库存，破坏、收集和放置要一致地更新世界、渲染与碰撞，不能穿过实体或把方块放进玩家身体。水应表现为水体并具有明确交互规则，火把可放置并发光；不要求复杂流体模拟。提供可用的相机与操作反馈，让玩家自由探索、挖掘和建造，不设唯一通关序列。input/reference.png 只作内容和视觉方向参考，不要求照抄构图或像素纹理；采用自己的材质与界面设计。固定游戏逻辑步长为 20 Hz，默认世界种子为 20260914，长度用 m。保存和读取后应恢复地形修改、玩家、库存及随机状态，并能继续游玩。

使用 Blender + UE5 制作这个游戏。提交完整、可编辑、可运行的 UE5 工程，包括 .uproject、游戏关卡、资产、配置及使用到的 Blueprint、C++ 源码、插件和依赖，默认关卡应能直接启动游玩。随附简短的启动与操作说明，并标明使用的引擎版本。项目内部组织、规则数据与存档格式由你选择。

## Fixed UE5 delivery contract

Submit the runnable project at `output/ue5_project/3DBenchGame.uproject`. The project root must contain `Config/` and `Content/`; `Source/`, `Plugins/`, and `SourceAssets/Blender/` are allowed when used. Put a short launch and controls note in `output/README.md`. Do not submit generated `Binaries/`, `Intermediate/`, `Saved/`, or `DerivedDataCache/` directories.

## 提供给模型的视觉参考

随输入提供 `input/reference.png` 和 `input/PROJECT_LAYOUT.md`。请参考图片中的几何风格、配色、相机构图和玩法可读性，制作风格协调的可玩三维游戏。这是生成的概念图，不是已实现游戏的截图，也不是几何 ground truth；不要求逐像素复刻、相同物体位置或相同 HUD 布局。尺寸、数量、物理、操作和流程以上面的文字要求为准，图片不会增加额外玩法要求。不能用整张图片贴在背景平面上代替可玩场景。
