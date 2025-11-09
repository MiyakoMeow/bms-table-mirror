mod filesystem;
mod logger;

use std::{
    fs,
    path::{Path, PathBuf},
};

use bms_table::fetch::reqwest::{fetch_table_full, fetch_table_index_full};
use log::{info, warn};

use crate::{filesystem::sanitize_filename, logger::init_logger};

const TABLE_INDEX_URL: &str = "https://script.google.com/macros/s/AKfycbzaQbcI9UZDcDlSHHl2NHilhmePrNrwxRdOFkmIXsfnbfksKKmAB3V65WZ8jPWU-7E/exec?table=tablelist";

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    init_logger();
    info!("Fetching table index from: {}", TABLE_INDEX_URL);
    let (indexes, original_json) = fetch_table_index_full(TABLE_INDEX_URL).await?;

    // Save original index JSON
    fs::write("table_original.json", &original_json)?;
    info!(
        "Saved original index JSON to table_original.json ({} bytes)",
        original_json.len()
    );

    // Prepare base output directory
    let base_dir = Path::new("tables");
    fs::create_dir_all(base_dir)?;

    // Fetch each table concurrently
    let mut join_set = tokio::task::JoinSet::new();
    for item in indexes {
        deal_with_index(&mut join_set, item, base_dir);
    }

    while let Some(_res) = join_set.join_next().await {}

    info!("All tasks finished.");
    Ok(())
}

fn deal_with_index(
    join_set: &mut tokio::task::JoinSet<()>,
    index: bms_table::BmsTableIndexItem,
    base_dir: &Path,
) {
    let url = index.url.to_string();
    // JoinSet 需要 'static future，捕获一个拥有所有权的 PathBuf
    let base_dir_owned = base_dir.to_path_buf();

    join_set.spawn(async move {
        if let Err(e) = fetch_and_save_table(&url, base_dir_owned.as_path()).await {
            warn!("Failed to fetch {} from {}: {}", index.name, url, e);
        } else {
            info!("Saved table {} from {}", index.name, url);
        }
    });
}

async fn fetch_and_save_table(
    web_url: &str,
    base_dir: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    // 先获取表数据与原始JSON，再创建目录与写入
    let (table, raw) = fetch_table_full(web_url).await?;

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
