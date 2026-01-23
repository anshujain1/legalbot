import { Container } from '../../components/Container/container'
import { Outlet } from 'react-router-dom';

export const Layout = () => {
  return (
    <Container>
      <Outlet />
    </Container>
  );
};
