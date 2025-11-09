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

#[derive(Clone)]
struct TableEntry {
    name: String,
    url: Url,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_logger();

    // Load configuration from tables.toml
    let config: TableConfig = load_table_config("tables.toml")?;

    // Build BTreeMap<Url, TableEntry>
    let mut index_map: BTreeMap<Url, TableEntry> = BTreeMap::new();

    let client = make_lenient_client()?;

    // Fetch and merge indexes from configured index endpoints
    for idx_url in &config.table_index_url {
        info!("Fetching table index from: {}", idx_url);
        let (indexes, _original_json) = fetch_table_index_full(&client, idx_url.as_str()).await?;
        for BmsTableIndexItem { name, url, .. } in indexes {
            let url_str = url.to_string();
            if let Ok(url) = Url::parse(&url_str) {
                index_map.insert(url.clone(), TableEntry { name, url });
            } else {
                warn!("Invalid URL in fetched index: {}", url_str);
            }
        }
    }

    // Add extra table URLs with default name from domain
    for url in &config.add_table_url {
        let name = url.host_str().unwrap_or("unknown").to_string();
        index_map.insert(
            url.clone(),
            TableEntry {
                name,
                url: url.clone(),
            },
        );
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
    index: TableEntry,
    base_dir: &Path,
) -> anyhow::Result<()> {
    let url = index.url.to_string();
    let name = index.name;
    // JoinSet 需要 'static future，捕获一个拥有所有权的 PathBuf
    let base_dir_owned = base_dir.to_path_buf();

    let client = make_lenient_client()?;

    join_set.spawn(async move {
        if let Err(e) = fetch_and_save_table(&client, &url, base_dir_owned.as_path()).await {
            warn!("Failed to fetch {} from {}: {}", name, url, e);
        } else {
            info!("Saved table {} from {}", name, url);
        }
    });

    Ok(())
}

async fn fetch_and_save_table(
    client: &reqwest::Client,
    web_url: &str,
    base_dir: &Path,
) -> anyhow::Result<()> {
    // 先获取表数据与原始JSON，再创建目录与写入
    let (table, raw) = fetch_table_full(client, web_url).await?;

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

    Ok(())
}
