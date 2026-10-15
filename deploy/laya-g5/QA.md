# 本轮交付检查

用户确认改用 g5.2xlarge 后，已完成东京 GPU 部署、76 次真实对比和报告更新。
最终资源检查确认实例 `i-0b93cd55e444dca0f` 为 running，HTTP 健康检查确认
多语言检查点在 CUDA 上运行、revision 匹配、CPU fallback 次数为 0。

## 离线校验

- 现有单元测试：19 个通过。
- 新 Python 文件语法解析、部署 shell 语法、`git diff --check` 通过。
- 使用 mock 验证实际 HTTP payload 只有模型控制参数、state 和 questions，不包含本地标准答案。
- 注入错误后只调用一次，保存错误并停止，不发第二个请求、不重试。
- 76 个请求无重复，两个 UI 修正输入与已有修正版一致。
- 报告生成成功；逐笔复核 76 份原始响应、请求指纹、Jev schema、逐题评分和耗时。
  147 个判断、71 个答对；不含对照组为 52/117；报表指标全部从回执计算。
- 上述 mock 仅检查运行器，不能视为模型表现或 GPU 验证。

## 页面检查

使用 `frontend-testing-debugging` 技能。Browser plugin not available，使用仓库已有的
Playwright 1.57.0 + Snap Chromium，保留浏览器沙箱。

流程：`report/index.html` → “Laya 专节” → `cost.html#laya-study`
→ 展开“全部 76 个未达标判断” → 显示 76 行原定标准及实际返回值。

检查 URL 为 `http://127.0.0.1:8766/report/`，桌面 1440×1000、手机 390×844。

| 项目 | 结果 |
|---|---|
| 页面标题、URL、非空内容 | 通过 |
| 总览跳转到 Laya 专节 | 通过 |
| 展开 details 后显示全部 76 个未达标判断 | 通过 |
| 新增内容在桌面和手机下可读 | 通过；表格允许横向滚动 |
| 页面脚本错误、框架错误覆盖层 | 无 |
| 图片缺失 | 无 |
| 控制台资源错误 | 无页面错误；原有 `/favicon.ico` 404 单独排除，报告 HTML/CSS 返回 200 |
| 全页手机宽度 | document 390px / viewport 390px，新增章节无越界元素 |

截图在 `/tmp/laya-report-qa/comparison-final.png`、`/tmp/laya-report-qa/laya-desktop-final.png`、
`/tmp/laya-report-qa/laya-mobile-final.png`。加入 Laya 后准确率范围扩大，已减少图表刻度密度，避免标签重叠。
页面原有其他场景没有重新跑浏览器业务闭环；Laya 闭环题仅做同状态回放，不宣称新闭环完成率。

## 真实 GPU 验证

- 独立中文预热 3/3 正确，首个冷请求 477.5 ms，后两个约 21 ms；不计入正式批次。
- 正式 76 次调用均成功，无重试；批次耗时 2.260264248 秒，中位 22.694 ms，P90 39.733 ms。
- 前后健康检查 CUDA、零 CPU fallback；147 题 state / instruction / options 均无 token 截断。
- 原始模型判断失败保留：76/147 未达标、24 个答错且直接选定、18 个高置信度错误。
- EC2 实例及 systemd 服务保留运行；推理仅监听 loopback，公网安全组只允许管理机 SSH。
- 管理机 SSH 本地转发后的 `/health` 验证通过；临时验证隧道已关闭。
