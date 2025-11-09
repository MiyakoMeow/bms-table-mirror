use std::{fs, path::PathBuf};

use bms_table::fetch::reqwest::{fetch_table_full, fetch_table_index_full};

const TABLE_INDEX_URL: &str = "https://script.google.com/macros/s/AKfycbzaQbcI9UZDcDlSHHl2NHilhmePrNrwxRdOFkmIXsfnbfksKKmAB3V65WZ8jPWU-7E/exec?table=tablelist";

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("Fetching table index from: {}", TABLE_INDEX_URL);
    let (indexes, original_json) = fetch_table_index_full(TABLE_INDEX_URL).await?;

    // Save original index JSON
    fs::write("table_original.json", &original_json)?;
    println!("Saved original index JSON to table_original.json ({} bytes)", original_json.len());

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
                eprintln!("Failed to fetch '{}' from {}: {}", out_dir.display(), url, e);
            } else {
                println!("Saved table '{}'", out_dir.display());
            }
        });
    }

    while let Some(_res) = join_set.join_next().await {}

    println!("All tasks finished.");
    Ok(())
}

async fn fetch_and_save_table(web_url: &str, out_dir: &PathBuf) -> Result<(), Box<dyn std::error::Error>> {
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
