use serde::Deserialize;
use std::fs;
use std::path::Path;
use url::Url;

#[derive(Debug, Deserialize)]
pub struct TableConfig {
    pub table_index_url: Vec<Url>,
    pub add_table_url: Vec<Url>,
    pub disable_table_url: Vec<Url>,
}

pub fn load_table_config<P: AsRef<Path>>(path: P) -> anyhow::Result<TableConfig> {
    let content = fs::read_to_string(path)?;
    let cfg: TableConfig = toml::from_str(&content)?;
    Ok(cfg)
}
