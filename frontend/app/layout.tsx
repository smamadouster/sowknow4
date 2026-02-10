export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body style={{ margin: 0, padding: 0, fontFamily: 'Arial, sans-serif' }}>
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
