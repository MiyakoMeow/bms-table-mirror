# bms-table-mirror

将远程 BMS 难度表镜像为本地的静态 JSON 文件集。通过配置多个索引端点与直连表页 URL，本工具并发抓取并生成可归档的目录结构，适合离线浏览、备份或下游处理。

## 功能概览
- 抓取并合并多个表索引端点（`table_index`），原始索引 JSON 同步保存至 `indexes/`。
- 直接添加额外表页 URL（`add_table_url`），无需索引端点即可拉取。
- 禁用指定表页 URL（`disable_table_url`），从最终抓取列表中移除。
- 为每个表生成目录：`tables/<表名经清洗>/`，包含：
  - `header.json`：原始 header JSON，自动将 `data_url` 替换为 `data.json`。
  - `data.json`：原始数据 JSON。
  - `info.json`：表的基本信息（源索引中的 `name/url/symbol` 等）。
- 自定义日志器：控制台输出 + 将 `warn` 级别写入根目录 `warnings.log`。
- 目录名自动清洗，兼容 Windows 文件系统的特殊字符与结尾规则。

## 目录结构
- 根目录文件：
  - `.gitignore`, `Cargo.toml`, `Cargo.lock`, `LICENSE`, `tables.toml`
  - 目录：`.github/workflows/`, `indexes/`, `src/`, `tables/`
- 生成产物：
  - `indexes/<索引名>.json`
  - `tables/<清洗后表名>/header.json`
  - `tables/<清洗后表名>/data.json`
  - `tables/<清洗后表名>/info.json`

## 快速开始
1) 安装 Rust（支持 edition 2024），推荐使用 `rustup`：
   - Windows/macOS/Linux 均可运行；需要可用的网络环境以访问表源。
2) 配置 `tables.toml`：
   ```toml
   table_index = [
     { name = "DARKSABUN", url = "https://script.google.com/macros/s/AKfycbzaQbcI9UZDcDlSHHl2NHilhmePrNrwxRdOFkmIXsfnbfksKKmAB3V65WZ8jPWU-7E/exec?table=tablelist" },
   ]

   add_table_url = [
     # 在此添加表页 URL，例如：
     # "https://example.com/my-bms-table"
   ]

   disable_table_url = [
     # 在此禁用某些表页 URL，例如：
     # "https://example.com/old-table"
   ]
   ```
3) 运行：
   - 开发模式：`cargo run`
   - 发布模式：`cargo run --release`

运行后将在根目录生成 `indexes/` 与 `tables/`。若网络响应较慢或表数量较多，首次运行可能耗时较长。

## 运行时日志
- 默认日志级别为 `info`，可通过环境变量调整：
  - Windows PowerShell：``$env:RUST_LOG = "warn"; cargo run --release``
  - Bash/zsh：``RUST_LOG=warn cargo run --release``
- `warn` 级别日志会额外写入根目录 `warnings.log`，便于筛查抓取失败或数据异常。

## 目录名清洗规则（Windows 兼容）
`src/filesystem.rs` 中的 `sanitize_filename` 将：
- 将非法字符（`<>:"/\|?*`）替换为对应全角字符，如 `:` → `：`。
- 将控制字符（ASCII ≤ 31）折叠为单个下划线 `_`。
- 若目录名以 `.` 或空格结尾，替换为全角 `．` 或 `　`，避免 Windows 封禁的结尾。

## 代码结构
- `src/main.rs`：入口；加载配置、抓取索引、合并 URL、并发拉取每张表，输出至 `indexes/` 与 `tables/`。
- `src/config.rs`：定义与解析 `tables.toml` 配置（`TableIndexSource`/`TableConfig`）。
- `src/filesystem.rs`：目录名清洗工具，保证跨平台文件系统兼容。
- `src/logger.rs`：自定义日志器，控制台输出 + `warn` 级别文件记录。

## 依赖与并发模型
- 主要依赖：`bms-table`, `reqwest`, `tokio`, `env_logger`, `log`, `serde`, `toml`, `anyhow`, `serde_json`。
- 并发：使用 `tokio::task::JoinSet` 并发抓取各表；失败不阻断其他任务，`warn` 级别记录错误信息。

## 常见问题
- 抓取失败/超时：检查网络环境或代理；失败会在控制台与 `warnings.log` 中出现。
- 重复运行：同名目录将被覆盖写入（文件用 `tokio::fs::write`），如需保留旧数据可手动备份。
- 规模较大：`tables/` 目录下可能包含大量难度表，建议在发布模式运行以提升性能。

## 许可证
本项目使用 `Apache-2.0` 许可证。详见根目录 `LICENSE` 文件。

## 致谢
- `bms-table` crate 提供了完整的表索引与数据抓取能力。
- 所有难度表与索引的版权归各自作者/站点所有，本工具仅提供镜像与归档用途。