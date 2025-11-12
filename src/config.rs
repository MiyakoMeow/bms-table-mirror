use std::path::Path;

use serde::{Deserialize, Serialize};
use url::Url;

#[derive(Debug, Serialize, Deserialize)]
pub struct TableListSource {
    pub name: String,
    pub url: Url,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct UrlReplaceRule {
    pub from: Url,
    pub to: Url,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct TableConfig {
    pub table_list: Vec<TableListSource>,
    #[serde(default)]
    pub add_table_url: Vec<Url>,
    #[serde(default)]
    pub disable_table_url: Vec<Url>,
    #[serde(default)]
    pub replace_table_url: Vec<UrlReplaceRule>,
}

pub async fn load_table_config<P: AsRef<Path>>(path: P) -> anyhow::Result<TableConfig> {
    let content = tokio::fs::read_to_string(path).await?;
    let cfg: TableConfig = toml::from_str(&content)?;
    Ok(cfg)
}
