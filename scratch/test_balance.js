const axios = require('axios');
const crypto = require('crypto');
const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '../.env') });

const API_KEY = process.env.BINANCE_API_KEY;
const API_SECRET = process.env.BINANCE_API_SECRET;
const TR_API_BASE = 'https://www.binance.tr';

function binanceSign(params) {
    const qs = new URLSearchParams({ ...params, timestamp: Date.now() }).toString();
    const sig = crypto.createHmac('sha256', API_SECRET).update(qs).digest('hex');
    return qs + '&signature=' + sig;
}

async function test() {
    try {
        const qs = binanceSign({});
        const url = `${TR_API_BASE}/open/v1/account/spot?${qs}`;
        console.log("Calling URL:", url);
        const res = await axios.get(url, {
            headers: {
                'X-MBX-APIKEY': API_KEY,
                'User-Agent': 'Mozilla/5.0'
            }
        });
        console.log("Full Raw Response:", JSON.stringify(res.data, null, 2));
    } catch (err) {
        console.error("Error:", err.message);
        if (err.response) {
            console.error("Response data:", err.response.data);
        }
    }
}

test();
