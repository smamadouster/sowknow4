export default function Home() {
  return (
    <div style={{ padding: '50px', fontFamily: 'Arial, sans-serif' }}>
      <h1>🚀 SOWKNOW4 Frontend is Running!</h1>
      <p>Multi-Generational Legacy Knowledge System</p>
      
      <div style={{ marginTop: '30px', padding: '20px', background: '#f5f5f5', borderRadius: '10px' }}>
        <h2>📊 System Status</h2>
        <ul>
          <li>✅ Backend API: <a href="http://localhost:8000" target="_blank">http://localhost:8000</a></li>
          <li>✅ API Documentation: <a href="http://localhost:8000/api/docs" target="_blank">http://localhost:8000/api/docs</a></li>
          <li>✅ PostgreSQL: localhost:5432</li>
          <li>✅ Redis: localhost:6379</li>
          <li>✅ Frontend: http://localhost:3000</li>
        </ul>
      </div>
    </div>
  )
}
