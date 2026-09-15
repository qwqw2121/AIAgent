import Link from 'next/link';

export default function Header() {
  return <header className="topbar">
    <Link href="/" className="brand"><span className="brand-mark">✦</span><span>AI News <i>Agent</i></span></Link>
    <nav><Link href="/">首页</Link><Link href="/trends">30天趋势</Link><Link href="/important">重要新闻</Link><Link href="/reports">日报列表</Link></nav>
  </header>;
}
