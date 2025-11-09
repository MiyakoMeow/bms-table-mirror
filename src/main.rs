use std::{fs, io::Write, path::PathBuf, sync::Mutex};

use bms_table::fetch::reqwest::{fetch_table_full, fetch_table_index_full};
use log::{info, warn};

struct DualLogger {
    inner: env_logger::Logger,
    warn_file: Option<Mutex<fs::File>>, // 仅记录 warn 级别到文件
}

impl log::Log for DualLogger {
    fn enabled(&self, metadata: &log::Metadata) -> bool {
        self.inner.enabled(metadata)
    }

    fn log(&self, record: &log::Record) {
        if self.enabled(record.metadata()) {
            // 保持原有行为：输出到控制台（由 env_logger 处理）
            self.inner.log(record);

            // 额外写入：将 warn 级别日志导出到根目录 warnings.log
            if record.level() == log::Level::Warn
                && let Some(f) = &self.warn_file
                && let Ok(mut file) = f.lock()
            {
                let _ = writeln!(file, "[WARN] {} - {}", record.target(), record.args());
            }
        }
    }

    fn flush(&self) {
        self.inner.flush();
        if let Some(f) = &self.warn_file
            && let Ok(mut file) = f.lock()
        {
            let _ = file.flush();
        }
    }
}

fn init_logger() {
    let inner =
        env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).build();

    // 打开根目录下的 warnings.log（失败不影响控制台日志）
    let warn_file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open("warnings.log")
        .ok()
        .map(Mutex::new);

    let dual = DualLogger { inner, warn_file };
    let _ = log::set_boxed_logger(Box::new(dual));
    // 放开最大级别，具体过滤由 inner.enabled 控制
    log::set_max_level(log::LevelFilter::Trace);
}

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

fn sanitize_filename(name: &str) -> String {
    // 将非法的非控制字符替换为对应的全角字符；控制字符替换为下划线
    let mapped: String = name
        .chars()
        .map(|c| match c {
            '<' => '＜',
            '>' => '＞',
            ':' => '：',
            '"' => '＂',
            '/' => '／',
            '\\' => '＼',
            '|' => '｜',
            '?' => '？',
            '*' => '＊',
            // 控制字符
            c if c as u32 <= 31 => '_',
            _ => c,
        })
        .collect();

    // 折叠连续下划线（可能来自多个控制字符）
    let mut collapsed = String::with_capacity(mapped.len());
    let mut last_was_us = false;
    for ch in mapped.chars() {
        if ch == '_' {
            if !last_was_us {
                collapsed.push(ch);
                last_was_us = true;
            }
        } else {
            collapsed.push(ch);
            last_was_us = false;
        }
    }

    // Windows 禁止以 '.' 或 ' ' 结尾，将结尾的这些字符替换为对应全角
    let s = collapsed;
    let mut run_start = s.len();
    let indices: Vec<(usize, char)> = s.char_indices().collect();
    for (pos, ch) in indices.iter().rev().copied() {
        if ch == '.' || ch == ' ' {
            run_start = pos;
        } else {
            break;
        }
    }
    if run_start < s.len() {
        let prefix = &s[..run_start];
        let suffix = &s[run_start..];
        let mut replaced = String::with_capacity(suffix.len());
        for ch in suffix.chars() {
            match ch {
                '.' => replaced.push('．'),
                ' ' => replaced.push('　'),
                _ => replaced.push(ch),
            }
        }
        format!("{}{}", prefix, replaced)
    } else {
        s
    }
}
