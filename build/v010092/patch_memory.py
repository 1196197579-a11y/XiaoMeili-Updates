from pathlib import Path
import sys
p=Path(sys.argv[1])/"app"/"src"/"main.py"
s=p.read_text(encoding="utf-8-sig")
old='''    def set_asset(self, label_idx, path, state):
        movie = QMovie(path)
        movie.setCacheMode(QMovie.CacheMode.CacheAll)
        movie.setScaledSize(self.size())
        if not movie.isValid():
            raise RuntimeError(f"动画素材无效: {path}")
        self.movie_generation += 1
        token = self.movie_generation
        # Imported WebP clips are finite. When one finishes, choose another clip
        # from the same state pool. Stale movies are ignored via generation token.
        movie.finished.connect(lambda tok=token, st=state: self._movie_finished(tok, st))
        self.movies[label_idx] = movie
        self.labels[label_idx].setMovie(movie)
        self.current_asset_path = path
        if state == "report" and hasattr(self, "report_overlay"):
            self.report_overlay.set_asset(path)
        movie.start()
'''
new='''    def set_asset(self, label_idx, path, state):
        old_movie = self.movies[label_idx] if 0 <= int(label_idx) < len(self.movies) else None
        if old_movie is not None:
            try: old_movie.stop()
            except Exception: pass
            try: self.labels[label_idx].clear()
            except Exception: pass
            try: old_movie.deleteLater()
            except Exception: pass
            self.movies[label_idx] = None
        movie = QMovie(path)
        movie.setCacheMode(QMovie.CacheMode.CacheNone)
        movie.setScaledSize(self.size())
        if not movie.isValid():
            try: movie.deleteLater()
            except Exception: pass
            raise RuntimeError(f"动画素材无效: {path}")
        self.movie_generation += 1
        token = self.movie_generation
        movie.finished.connect(lambda tok=token, st=state: self._movie_finished(tok, st))
        self.movies[label_idx] = movie
        self.labels[label_idx].setMovie(movie)
        self.current_asset_path = path
        if state == "report" and hasattr(self, "report_overlay"):
            self.report_overlay.set_asset(path)
        movie.start()
'''
if old not in s: raise RuntimeError("set_asset anchor missing")
s=s.replace(old,new,1)
p.write_text(s,encoding="utf-8",newline="\n")
print("MEMORY_PATCH_PASS")
