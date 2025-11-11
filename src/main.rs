mod config;
mod filesystem;
mod logger;

use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    time::Duration,
};
use tokio::fs;

use anyhow::{Result, anyhow};
use bms_table::{
    BmsTable, BmsTableData, BmsTableHeader, BmsTableInfo, BmsTableRaw,
    fetch::reqwest::{fetch_table_full, fetch_table_list_full},
};
use log::{info, warn};
use url::Url;

use crate::{
    config::{TableConfig, load_table_config},
    filesystem::{deep_sort_json_value, is_changed, sanitize_filename},
    logger::init_logger,
};

#[tokio::main]
async fn main() -> Result<()> {
    init_logger();

    // Load configuration from tables.toml
    let config: TableConfig = load_table_config("tables.toml").await?;

    // Build BTreeMap<Url, BmsTableInfo>
    let mut table_info_map: BTreeMap<Url, BmsTableInfo> = BTreeMap::new();

    // Prepare index output directory
    let lists_dir = Path::new("lists");
    fs::create_dir_all(lists_dir).await?;

    let client = make_lenient_client()?;

    // Fetch and merge indexes from configured index endpoints
    for idx in &config.table_list {
        // Fetch table list
        info!("Fetching table index from: {} ({})", idx.name, idx.url);
        let (infos, original_json) = fetch_table_list_full(&client, idx.url.as_str()).await?;
        // Write list json file
        let list_file_path = lists_dir.join(format!("{}.json", idx.name));
        fs::write(list_file_path, original_json).await?;
        // Yield into table_info_map
        for info in infos {
            let url_str = info.url.to_string();
            let Ok(url) = Url::parse(&url_str) else {
                warn!("Invalid URL in fetched index: {}", url_str);
                continue;
            };
            table_info_map.insert(url.clone(), info);
        }
    }

    // Add extra table URLs with default name from domain
    for url in &config.add_table_url {
        let name = url.host_str().unwrap_or("unknown").to_string();
        // 手动构建 BmsTableInfo，symbol 使用 "-"
        let item = BmsTableInfo {
            name,
            url: url.clone(),
            symbol: "-".to_string(),
            extra: Default::default(),
        };
        let Ok(k) = Url::parse(item.url.as_ref()) else {
            warn!("Invalid URL in add_table_url: {}", url);
            continue;
        };
        table_info_map.insert(k, item);
    }

    // Disable specified table URLs
    for url in &config.disable_table_url {
        if table_info_map.remove(url).is_some() {
            info!("Disabled table: {}", url);
        }
    }

    // Prepare base output directory
    let base_dir = Path::new("tables");
    fs::create_dir_all(base_dir).await?;

    // Fetch each table concurrently based on built map
    let mut join_set = tokio::task::JoinSet::new();
    for info in table_info_map.into_values() {
        spawn_fetch(&mut join_set, info, base_dir)?;
    }

    while let Some(_res) = join_set.join_next().await {}

    info!("All tasks finished.");
    Ok(())
}

fn spawn_fetch(
    join_set: &mut tokio::task::JoinSet<()>,
    info: BmsTableInfo,
    base_dir: &Path,
) -> Result<()> {
    let url = info.url.to_string();
    let name = info.name.clone();
    // JoinSet 需要 'static future，捕获一个拥有所有权的 PathBuf
    let base_dir_owned = base_dir.to_path_buf();

    let client = make_lenient_client()?;

    join_set.spawn(async move {
        let idx = info;
        if let Err(e) = fetch_and_save_table(&client, idx, base_dir_owned.as_path()).await {
            warn!("Failed to fetch {} from {}: {}", name, url, e);
        } else {
            info!("Saved table {} from {}", name, url);
        }
    });

    Ok(())
}

async fn fetch_and_save_table(
    client: &reqwest::Client,
    mut info: BmsTableInfo,
    base_dir: &Path,
) -> Result<()> {
    // 先获取表数据与原始JSON，再创建目录与写入
    let (
        BmsTable { header, data: _ },
        BmsTableRaw {
            header_raw,
            data_raw,
            header_json_url,
            data_json_url,
        },
    ) = fetch_table_full(client, info.url.as_str()).await?;

    // 使用 BmsTableHeader 的 name 作为目录名（经 sanitize）
    let dir_name = sanitize_filename(&header.name);
    let out_dir = base_dir.join(dir_name);

    // 使用 BmsTableHeader 的 data_url 字段，直接用 String::replace 将其替换为 "data.json"
    let patched_header = header_raw.replace(&header.data_url, "data.json");

    // 在成功获取后再创建目录与写入文件
    fs::create_dir_all(&out_dir).await?;
    let header_path: PathBuf = out_dir.join("header.json");
    let data_path = out_dir.join("data.json");

    // 条件写入：仅在解析失败或对象不同的情况下替换
    if is_changed::<BmsTableHeader>(&header_path, &patched_header, |header| {
        header.extra = Default::default()
    })
    .await?
    {
        fs::write(&header_path, &patched_header).await?;
    }
    if is_changed::<BmsTableData>(&data_path, &data_raw, |data| {
        data.charts
            .iter_mut()
            .for_each(|v| v.extra = Default::default())
    })
    .await?
    {
        fs::write(&data_path, &data_raw).await?;
    }

    // 向info同步实际获取的难度表信息
    info.name = header.name;
    info.symbol = header.symbol;

    // 向info的extra字段写入header_json_url和data_json_url
    *info.extra.entry("header_json_url".to_string()).or_default() =
        serde_json::to_value(header_json_url)?;
    *info.extra.entry("data_json_url".to_string()).or_default() =
        serde_json::to_value(data_json_url)?;

    // 写入info
    let info_path: PathBuf = out_dir.join("info.json");
    let info_data = serde_json::to_string_pretty(&info)?;
    if is_changed::<serde_json::Value>(&info_path, &info_data, deep_sort_json_value).await? {
        fs::write(&info_path, &info_data).await?;
    }

    Ok(())
}

/// 创建一个规则宽松、兼容性更强的 HTTP 客户端。
///
/// - 设置浏览器 UA；
/// - 配置超时与重定向；
/// - 接受无效证书（用于少数不规范站点）；
/// - 接受无效主机名（用于少数不规范站点）；
///
/// 注意：生产环境应审慎使用 `danger_accept_invalid_certs`。
pub fn make_lenient_client() -> Result<reqwest::Client> {
    let client = reqwest::Client::builder()
        .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119 Safari/537.36 bms-table-rs")
        .timeout(Duration::from_secs(60))
        .redirect(reqwest::redirect::Policy::limited(100))
        .danger_accept_invalid_certs(true)
        .danger_accept_invalid_hostnames(true)
        .build()
        .map_err(|e| anyhow!("When building client: {e}"))?;
    Ok(client)
}
