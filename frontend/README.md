# KubeFreezer Frontend

React + TypeScript frontend for KubeFreezer deployment freeze management.

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool
- **Tailwind CSS** - Styling
- **React Router** - Routing
- **Lucide React** - Icons

## Development

### Prerequisites

- Node.js 18+
- npm or yarn

### Setup

```bash
# Install dependencies
npm install

# Start development server
npm run dev
```

The frontend will run on `http://localhost:5173` and proxy API requests to the backend.

### Backend Setup

Make sure the backend is running:

```bash
# In another terminal
cd ../app
uvicorn main:app --reload --port 8443
```

## Building

```bash
# Build for production
npm run build

# Output: dist/
```

## Docker Build

```bash
# Build frontend image
docker build -t kubefreezer-ui:latest .

# Or from project root
cd ..
docker build -f frontend/Dockerfile -t kubefreezer-ui:latest frontend/
```

## Project Structure

```
frontend/
├── src/
│   ├── components/     # React components
│   ├── pages/          # Page components
│   ├── services/       # API client & auth
│   ├── hooks/          # Custom React hooks
│   └── types/          # TypeScript types
├── public/             # Static assets
├── Dockerfile          # Nginx-based production image
└── nginx.conf          # Nginx configuration
```

## Authentication

The frontend uses API key authentication:

1. User enters API key on login page
2. Key is stored in localStorage
3. Key is sent in `Authorization: Bearer <key>` header for all API requests
4. On 401 error, user is redirected to login

## API Integration

All API calls go through `/api/v1/*` which is:
- In development: Proxied to `http://localhost:8443` (via vite.config.ts)
- In production: Proxied to backend service (via nginx.conf)

## Pages

- **Login** (`/login`) - API key authentication
- **Dashboard** (`/dashboard`) - Freeze status overview
- **Templates** (`/templates`) - List and apply templates
- **Schedules** (`/schedules`) - View and manage schedules
- **Exemptions** (`/exemptions`) - Manage exemptions
- **History** (`/history`) - View event history

