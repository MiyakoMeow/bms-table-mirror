use serde::Deserialize;
use std::path::Path;
use url::Url;

#[derive(Debug, Deserialize)]
pub struct TableListSource {
    pub name: String,
    pub url: Url,
}

#[derive(Debug, Deserialize)]
pub struct TableConfig {
    pub table_list: Vec<TableListSource>,
    pub add_table_url: Vec<Url>,
    pub disable_table_url: Vec<Url>,
}

pub async fn load_table_config<P: AsRef<Path>>(path: P) -> anyhow::Result<TableConfig> {
    let content = tokio::fs::read_to_string(path).await?;
    let cfg: TableConfig = toml::from_str(&content)?;
    Ok(cfg)
}
