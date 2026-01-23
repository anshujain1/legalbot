import styles from './container.module.css';
import { Navbar } from '../../components/navbar';

export const Container: React.FC<React.PropsWithChildren> = (props) => {
  return (
    <div className={styles['background']}>
      <Navbar />
      <div className={styles['container']}>{props.children}</div>
    </div>
  );
};
