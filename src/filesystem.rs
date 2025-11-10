use std::path::Path;

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

/// 仅在需要时写入 JSON 文件：
/// - 文件不存在；或
/// - 旧文件解析失败；或
/// - 解析后对象不同。
pub fn write_json_if_changed(path: &Path, new_content: &str) -> anyhow::Result<()> {
    use serde_json::Value;
    use std::fs;

    if !path.exists() {
        // 路径下文件不存在，直接写入
        fs::write(path, new_content)?;
        return Ok(());
    }
    // 读取旧文件内容
    let Ok(old_str) = fs::read_to_string(path) else {
        // 文件读取失败，直接写入
        fs::write(path, new_content)?;
        return Ok(());
    };
    // 解析json
    let old_parsed = serde_json::from_str::<Value>(&old_str);
    let new_parsed = serde_json::from_str::<Value>(new_content);
    match (old_parsed, new_parsed) {
        // 如果旧文件和新文件解析后对象相等，则不写入
        (Ok(mut old_val), Ok(mut new_val)) => {
            old_val.sort_all_objects();
            new_val.sort_all_objects();
            if old_val != new_val {
                fs::write(path, new_content)?;
            }
        }
        // 旧文件不相等、解析失败或无法比较，直接替换
        _ => {
            fs::write(path, new_content)?;
        }
    }
    Ok(())
}
