mod filesystem;
mod logger;

use std::{fs, path::PathBuf};

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
    let base_dir = PathBuf::from("tables");
    fs::create_dir_all(&base_dir)?;

    // Fetch each table concurrently
    let mut join_set = tokio::task::JoinSet::new();
    for item in indexes {
        let name = sanitize_filename(&item.name);
        let out_dir = base_dir.join(name);
        let url = item.url.to_string();

        join_set.spawn(async move {
            if let Err(e) = fetch_and_save_table(&url, &out_dir).await {
                warn!(
                    "Failed to fetch '{}' from {}: {}",
                    out_dir.display(),
                    url,
                    e
                );
            } else {
                info!("Saved table '{}'", out_dir.display());
            }
        });
    }

    while let Some(_res) = join_set.join_next().await {}

    info!("All tasks finished.");
    Ok(())
}

async fn fetch_and_save_table(
    web_url: &str,
    out_dir: &PathBuf,
) -> Result<(), Box<dyn std::error::Error>> {
    fs::create_dir_all(out_dir)?;

    let (_table, raw) = fetch_table_full(web_url).await?;

    let header_path = out_dir.join("header.json");
    let data_path = out_dir.join("data.json");

    fs::write(&header_path, raw.header_raw)?;
    fs::write(&data_path, raw.data_raw)?;

    Ok(())
}
