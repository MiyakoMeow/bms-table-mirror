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
