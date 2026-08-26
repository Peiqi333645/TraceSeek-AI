import { Children, cloneElement, createContext, isValidElement, useContext, useEffect, useState } from 'react'

const RouterContext = createContext({ path: '/', go: () => {} })

export function BrowserRouter({ children }) {
  const [path, setPath] = useState(() => window.location.pathname || '/')
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname || '/')
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const go = (to, replace = false) => {
    window.history[replace ? 'replaceState' : 'pushState']({}, '', to)
    setPath(to)
  }
  return <RouterContext.Provider value={{ path, go }}>{children}</RouterContext.Provider>
}

export function Link({ to, onClick, children, ...props }) {
  const { go } = useContext(RouterContext)
  return <a href={to} {...props} onClick={(e) => { e.preventDefault(); onClick?.(e); go(to) }}>{children}</a>
}

export function NavLink({ to, className, children, ...props }) {
  const { path, go } = useContext(RouterContext)
  const active = path === to
  return <a href={to} {...props} className={typeof className === 'function' ? className({ isActive: active }) : className}
    onClick={(e) => { e.preventDefault(); go(to) }}>{children}</a>
}

export function Navigate({ to, replace = false }) {
  const { go } = useContext(RouterContext)
  useEffect(() => { go(to, replace) }, [to, replace])
  return null
}

export function Route() { return null }

export function Routes({ children }) {
  const { path } = useContext(RouterContext)
  const routes = Children.toArray(children).filter(isValidElement)
  const match = routes.find((r) => r.props.path === path) || routes.find((r) => r.props.path === '*')
  return match ? cloneElement(match.props.element) : null
}
