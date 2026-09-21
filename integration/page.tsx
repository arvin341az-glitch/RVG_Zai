export default function Home() {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        gap: '1rem',
        padding: '2rem',
        fontFamily: 'system-ui, sans-serif',
        background: '#0A0E15',
        color: '#E9EEF7',
        textAlign: 'center',
      }}
    >
      <h1 style={{ fontSize: '1.75rem', fontWeight: 700 }}>RVG Gateway</h1>
      <p style={{ color: '#9AA6BE' }}>Redirecting to panel…</p>
      <script
        dangerouslySetInnerHTML={{
          __html: `setTimeout(function(){window.location.href='/dashboard';},1000);`,
        }}
      />
    </div>
  );
}
