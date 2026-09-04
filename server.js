const express = require('express');
const cors = require('cors');

const app = express();
const PORT = 8000;

app.use(cors());
app.use(express.json());

// Lưu trữ tọa độ, mật khẩu, ping và chỉ số
const rooms = {};

app.post('/sync', (req, res) => {
    const { room_code, password, player_id, name, x, y, yaw, ping, vitals } = req.body;

    if (!room_code || password === undefined || !player_id || x === undefined || y === undefined) {
        return res.status(400).json({ detail: "Thiếu dữ liệu đầu vào!" });
    }

    const now = Date.now() / 1000;

    if (!rooms[room_code]) {
        rooms[room_code] = {
            password: password,
            players: {}
        };
    }

    if (rooms[room_code].password !== password) {
        return res.status(403).json({ detail: "Sai mật khẩu phòng!" });
    }

    // Lưu toàn bộ dữ liệu vị trí, tên, ping, và chỉ số sinh tồn của người gửi
    rooms[room_code].players[player_id] = { 
        name: name || player_id, 
        x, y, yaw, 
        ping: ping || null,
        vitals: vitals || null,
        last_seen: now 
    };

    const teammates = [];
    const inactivePlayers = [];

    for (const [pid, info] of Object.entries(rooms[room_code].players)) {
        if (now - info.last_seen > 10) {
            inactivePlayers.push(pid);
        } else if (pid !== player_id) {
            teammates.push({ 
                id: pid, 
                name: info.name, 
                x: info.x, 
                y: info.y, 
                yaw: info.yaw,
                ping: info.ping,
                vitals: info.vitals
            });
        }
    }

    inactivePlayers.forEach(pid => delete rooms[room_code].players[pid]);

    if (Object.keys(rooms[room_code].players).length === 0) {
        delete rooms[room_code];
    }

    res.json({ teammates });
});

app.listen(PORT, '0.0.0.0', () => {
    console.log(`Node.js Party Server đang chạy tại cổng ${PORT}`);
});