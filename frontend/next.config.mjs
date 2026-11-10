/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      { source: '/app', destination: '/workspace/growthrova.html' },
      { source: '/app/:path*', destination: '/workspace/growthrova.html' },
      { source: '/app-v2', destination: '/workspace/growthrova.html' },
      { source: '/growthrova.html', destination: '/workspace/growthrova.html' },
    ];
  },
  async headers() {
    return [{ source: '/app/:path*', headers: [{key:'Cache-Control',value:'no-store'}] },{ source: '/app-v2', headers: [{key:'Cache-Control',value:'no-store'}] }];
  },
};
export default nextConfig;
