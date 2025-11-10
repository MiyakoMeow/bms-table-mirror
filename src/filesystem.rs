use std::path::Path;

use log::{info, warn};
use serde_json::Value;

pub fn sanitize_filename(name: &str) -> String {
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

/// 递归排序 serde_json::Value：
/// - 遇到数组：先对每个元素递归处理并调用 sort_all_objects，然后按字符串表示排序；
/// - 遇到对象：先递归处理其值并调用 sort_all_objects，最后对当前对象执行 sort_all_objects；
/// - 其他类型：不处理。
pub fn deep_sort_json_value(value: &mut Value) {
    match value {
        Value::Array(arr) => {
            // 排序数组元素
            arr.iter_mut().for_each(deep_sort_json_value);
            // 数组元素排序，确保比较稳定
            arr.sort_by_key(|a| a.to_string());
        }
        Value::Object(map) => {
            // 排序对象值
            map.values_mut().for_each(deep_sort_json_value);
            // 对当前Map的key执行排序，确保键顺序稳定
            map.sort_keys();
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
}

/// 仅在需要时写入 JSON 文件：
/// - 文件不存在；或
/// - 旧文件解析失败；或
/// - 解析后对象不同。
pub async fn write_json_if_changed(path: &Path, new_content: &str) -> anyhow::Result<()> {
    use serde_json::Value;
    use tokio::fs;

    if !fs::try_exists(path).await? {
        // 路径下文件不存在，直接写入
        fs::write(path, new_content).await?;
        return Ok(());
    }
    // 读取旧文件内容
    let Ok(old_str) = fs::read_to_string(path).await else {
        // 文件读取失败，直接写入
        warn!("旧文件 {:?} 读取失败，尝试执行覆盖写入", path);
        fs::write(path, new_content).await?;
        return Ok(());
    };
    // 解析json
    let old_parsed = serde_json::from_str::<Value>(&old_str);
    let new_parsed = serde_json::from_str::<Value>(new_content);

    // 解析失败，直接写入新文件
    let Ok(mut old_val) = old_parsed else {
        warn!("旧文件 {:?} 解析失败，尝试执行覆盖写入", path);
        fs::write(path, new_content).await?;
        return Ok(());
    };
    let Ok(mut new_val) = new_parsed else {
        warn!("新文件 {:?} 解析失败，尝试执行覆盖写入", path);
        fs::write(path, new_content).await?;
        return Ok(());
    };

    // 解析成功，进行递归排序后比较是否不同
    deep_sort_json_value(&mut old_val);
    deep_sort_json_value(&mut new_val);

    // 排序后比较是否不同
    if old_val != new_val {
        info!("旧文件 {:?} 与新文件 {:?} 不同，写入新文件", path, path);
        fs::write(path, new_content).await?;
    }
    Ok(())
}
