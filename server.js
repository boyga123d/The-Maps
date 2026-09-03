const express = require('express');
const cors = require('cors');

const app = express();
const PORT = 8000;

// Bật CORS để cho phép kết nối từ mọi nguồn
app.use(cors());
app.use(express.json());

// Lưu trữ tọa độ và mật khẩu:
// { "room_code": { "password": "...", "players": { "pid": {x, y, yaw, last_seen} } } }
const rooms = {};

app.post('/sync', (req, res) => {
    const { room_code, password, player_id, x, y, yaw } = req.body;

    if (!room_code || password === undefined || !player_id || x === undefined || y === undefined) {
        return res.status(400).json({ detail: "Thiếu dữ liệu đầu vào!" });
    }

    const now = Date.now() / 1000; // Thời gian hiện tại (giây)

    // 1. Tạo phòng nếu chưa tồn tại
    if (!rooms[room_code]) {
        rooms[room_code] = {
            password: password,
            players: {}
        };
    }

    // 2. Kiểm tra mật khẩu (Báo lỗi 403 nếu sai để app.py nhận diện và ngắt)
    if (rooms[room_code].password !== password) {
        return res.status(403).json({ detail: "Sai mật khẩu phòng!" });
    }

    // 3. Cập nhật vị trí của người chơi hiện tại
    rooms[room_code].players[player_id] = { x, y, yaw, last_seen: now };

    const teammates = [];
    const inactivePlayers = [];

    // 4. Lọc đồng đội và dọn dẹp người chơi AFK (>10 giây không update)
    for (const [pid, info] of Object.entries(rooms[room_code].players)) {
        if (now - info.last_seen > 10) {
            inactivePlayers.push(pid);
        } else if (pid !== player_id) {
            teammates.push({ id: pid, x: info.x, y: info.y, yaw: info.yaw });
        }
    }

    inactivePlayers.forEach(pid => delete rooms[room_code].players[pid]);

    // 5. Giải phóng bộ nhớ: Xóa phòng nếu không còn ai
    if (Object.keys(rooms[room_code].players).length === 0) {
        delete rooms[room_code];
    }

    // Trả về danh sách đồng đội
    res.json({ teammates });
});

// Chạy server trên mọi giao diện mạng (0.0.0.0)
app.listen(PORT, '0.0.0.0', () => {
    console.log(`Node.js Party Server đang chạy tại cổng ${PORT}`);
});