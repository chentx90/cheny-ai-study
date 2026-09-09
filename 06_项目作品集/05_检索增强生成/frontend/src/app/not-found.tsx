export default function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">404</h1>
        <p className="text-gray-600 mb-6">页面未找到</p>
        <a href="/" className="text-blue-600 hover:underline">返回首页</a>
      </div>
    </div>
  )
}
