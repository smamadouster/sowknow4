export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <title>SOWKNOW4 - Legacy Knowledge System</title>
        <style>{`
          body { margin: 0; padding: 0; font-family: Arial, sans-serif; }
          button { padding: 10px 20px; background: #0070f3; color: white; border: none; border-radius: 5px; cursor: pointer; }
          button:hover { background: #0051a8; }
          a { color: #0070f3; text-decoration: none; }
          a:hover { text-decoration: underline; }
        `}</style>
      </head>
      <body>
        <nav style={{ background: '#333', color: 'white', padding: '20px' }}>
          <h1 style={{ margin: 0 }}>SOWKNOW4</h1>
          <p style={{ margin: '5px 0 0 0', opacity: 0.8 }}>Multi-Generational Legacy Knowledge System</p>
        </nav>
        <main>{children}</main>
        <footer style={{ marginTop: '50px', padding: '20px', background: '#f5f5f5', textAlign: 'center' }}>
          <p>SOWKNOW4 - Phase 1: Core MVP | Development Environment</p>
        </footer>
      </body>
    </html>
  )
}
