import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
  allowedDevOrigins: [
    "172.21.85.132",   // WSL 内部 IP
    "192.168.0.109",     // 你 Windows 的局域网 IP（替换成 ipconfig 里查到的实际值）
    "31f7de0d.r16.cpolar.top", // cpolar 生成的公网域名（替换成实际的）
  ],
};
export default nextConfig;
