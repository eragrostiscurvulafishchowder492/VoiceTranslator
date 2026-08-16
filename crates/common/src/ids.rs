//! 短 ID 生成（节点/管线/请求）。
use uuid::Uuid;

pub fn new_id(prefix: &str) -> String {
    let mut s = Uuid::new_v4().simple().to_string();
    s.truncate(8);
    format!("{prefix}_{s}")
}
