mod config;
mod filesystem;
mod logger;

use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};

use bms_table::{
    BmsTableIndexItem,
    fetch::reqwest::{fetch_table_full, fetch_table_index_full, make_lenient_client},
};
use log::{info, warn};
use url::Url;

use crate::config::{TableConfig, load_table_config};
use crate::{filesystem::sanitize_filename, logger::init_logger};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_logger();

    // Load configuration from tables.toml
    let config: TableConfig = load_table_config("tables.toml")?;

    // Build BTreeMap<Url, BmsTableIndexItem>
    let mut index_map: BTreeMap<Url, BmsTableIndexItem> = BTreeMap::new();

    // Prepare index output directory
    let index_dir = Path::new("indexes");
    fs::create_dir_all(index_dir)?;

    let client = make_lenient_client()?;

    // Fetch and merge indexes from configured index endpoints
    for idx in &config.table_index {
        info!("Fetching table index from: {} ({})", idx.name, idx.url);
        let (indexes, original_json) = fetch_table_index_full(&client, idx.url.as_str()).await?;
        for item in indexes {
            let url_str = item.url.to_string();
            if let Ok(url) = Url::parse(&url_str) {
                index_map.insert(url.clone(), item);
            } else {
                warn!("Invalid URL in fetched index: {}", url_str);
            }
        }
        // Write index json file
        let index_file_path = index_dir.join(format!("{}.json", idx.name));
        fs::write(index_file_path, original_json)?;
    }

    // Add extra table URLs with default name from domain
    for url in &config.add_table_url {
        let name = url.host_str().unwrap_or("unknown").to_string();
        // 手动构建 BmsTableIndexItem，symbol 使用 "-"
        let item = BmsTableIndexItem {
            name,
            url: url.clone(),
            symbol: "-".to_string(),
            extra: Default::default(),
        };
        if let Ok(k) = Url::parse(item.url.as_ref()) {
            index_map.insert(k, item);
        } else {
            warn!("Invalid URL in add_table_url: {}", url);
        }
    }

    // Disable specified table URLs
    for url in &config.disable_table_url {
        if index_map.remove(url).is_some() {
            info!("Disabled table: {}", url);
        }
    }

    // Prepare base output directory
    let base_dir = Path::new("tables");
    fs::create_dir_all(base_dir)?;

    // Fetch each table concurrently based on built map
    let mut join_set = tokio::task::JoinSet::new();
    for (_url, idx) in index_map {
        spawn_fetch(&mut join_set, idx, base_dir)?;
    }

    while let Some(_res) = join_set.join_next().await {}

    info!("All tasks finished.");
    Ok(())
}

fn spawn_fetch(
    join_set: &mut tokio::task::JoinSet<()>,
    index: BmsTableIndexItem,
    base_dir: &Path,
) -> anyhow::Result<()> {
    let url = index.url.to_string();
    let name = index.name.clone();
    // JoinSet 需要 'static future，捕获一个拥有所有权的 PathBuf
    let base_dir_owned = base_dir.to_path_buf();

    let client = make_lenient_client()?;

    join_set.spawn(async move {
        let idx = index;
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
    mut index: BmsTableIndexItem,
    base_dir: &Path,
) -> anyhow::Result<()> {
    // 先获取表数据与原始JSON，再创建目录与写入
    let (table, raw) = fetch_table_full(client, index.url.as_str()).await?;

    // 使用 BmsTableHeader 的 name 作为目录名（经 sanitize）
    let dir_name = sanitize_filename(&table.header.name);
    let out_dir = base_dir.join(dir_name);

    // 使用 BmsTableHeader 的 data_url 字段，直接用 String::replace 将其替换为 "data.json"
    let patched_header = raw.header_raw.replace(&table.header.data_url, "data.json");

    // 在成功获取后再创建目录与写入文件
    fs::create_dir_all(&out_dir)?;
    let header_path: PathBuf = out_dir.join("header.json");
    let data_path: PathBuf = out_dir.join("data.json");

    fs::write(&header_path, patched_header)?;
    fs::write(&data_path, raw.data_raw)?;

    // 向index同步实际获取的难度表信息
    index.name = table.header.name;
    index.symbol = table.header.symbol;

    // 写入index
    let info_path: PathBuf = out_dir.join("info.json");
    let info_data = serde_json::to_string_pretty(&index)?;
    fs::write(&info_path, info_data)?;

    Ok(())
}
