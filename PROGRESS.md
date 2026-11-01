# 任务 A 进度

- 已阅读 BAM 的远程环境方案和 CNB 两轮实测文档，确认 Manager 默认关闭远程能力。
- 已在 `feat/remote-environment` 增加 `proxy_chain`、registry restore/push、mihomo per-profile、空闲停止和 `GET /api/environment`。
- Manager commit `91c813c` 已推送到 GitHub 分支。
- CNB 仓库 `shellus666/browser-runtime` 已切换 `feat/remote-environment` 镜像分支并在启动阶段运行 Manager，commit `0b5d45a` 已推送。
- 验证：Python 语法检查通过；pytest 因当前 Python 环境缺少 `fastapi` 未能收集。
- 待后续：使用 CNB API 冷启动并完成真实 Profile/Gmail 闭环，记录预览地址与 token 本地文件位置。
